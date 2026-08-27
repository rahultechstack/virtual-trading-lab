"""Backtest engine.

    candles -> indicators -> strategy -> sizing -> execution -> portfolio

Runs a strategy over historical candles using the live trading system's own
execution and accounting code, so a backtest and a real account are priced and
measured identically.

**Fill timing.** A signal produced from bar N's close cannot execute at that
same close -- you only know the close once the bar is over. By default the
order fills against bar N+1's **open**, which is the first price actually
tradable after the decision.

``FillTiming.CURRENT_CLOSE`` is available for comparison, but it assumes a
price that was not knowable at the moment of the decision, which is lookahead
bias. It does not always *flatter* a run -- on a losing strategy it can read
worse -- but it is not a result that could have been achieved, which is the
point.

**No lookahead.** The strategy sees history only up to the current bar; see
``StrategyContext``.

**Asset classes.** The engine iterates the bars it is given and asserts nothing
about when they occur -- there is no weekday filter, no session-hours check and
no 252-day annualisation anywhere in it. A 24/7 crypto series with Saturday and
Sunday bars therefore runs correctly with no special case, and so does an NSE
series with none. Two things do come from the instrument:

* **Sizing.** ``PositionSizer`` rounds down to the instrument's
  ``quantity_step``. Without this a percent-of-equity run on BTC would size
  ``int(950000 / 7600000)`` = **0** and never trade at all.
* **Charges.** Fills are priced with the fee schedule for the instrument's
  asset class, so a crypto backtest is not charged STT.

The instrument's calendar is recorded on the result (``trading_calendar``) so a
reader can tell a 24/7 run from a session-bound one.
"""

from dataclasses import dataclass
from decimal import Decimal
from enum import StrEnum

from app.backtest.portfolio import BacktestPortfolio, InsufficientCash
from app.backtest.results import BacktestResult, summarise
from app.core.config import settings
from app.core.logging import get_logger
from app.indicators.service import IndicatorService
from app.market_data.instruments import (
    AssetClass,
    Instrument,
    resolve_instrument,
)
from app.markets.registry import calendar_for
from app.models.enums import OrderSide
from app.schemas.market_data import Candle
from app.strategies.base import Decision, Signal, Strategy, StrategyContext
from app.trading.execution import ExecutionEngine
from app.trading.fees import FeeCalculator
from app.trading.slippage import SlippageModel
from app.trading.spread import SpreadModel

logger = get_logger(__name__)

ZERO = Decimal("0.00")


class FillTiming(StrEnum):
    """When a signal becomes a fill."""

    #: Fill against the next bar's open. Realistic, and the default.
    NEXT_OPEN = "next_open"
    #: Fill against the bar that produced the signal. Lookahead: that price
    #: was not knowable when the decision was made.
    CURRENT_CLOSE = "current_close"


class SizingMode(StrEnum):
    """How large a new position should be."""

    FIXED_QUANTITY = "fixed_quantity"
    FIXED_VALUE = "fixed_value"
    PERCENT_OF_EQUITY = "percent_of_equity"


@dataclass(frozen=True)
class BacktestConfig:
    """Everything that is not the strategy or the data."""

    initial_capital: Decimal = Decimal("1000000.00")
    fill_timing: FillTiming = FillTiming.NEXT_OPEN

    sizing_mode: SizingMode = SizingMode.PERCENT_OF_EQUITY
    #: Used by PERCENT_OF_EQUITY. Below 100 to leave room for charges.
    equity_percent: Decimal = Decimal("95")
    fixed_quantity: Decimal = Decimal("100")
    fixed_value: Decimal = Decimal("100000.00")

    #: Close any open position on the final bar, so the result is not
    #: dominated by an unrealized number that was never taken.
    close_at_end: bool = True


class PositionSizer:
    """Decides how large an order is, in the instrument's own units.

    Sizes are rounded **down** to the instrument's tradable increment, so a
    stock gets whole shares and crypto gets a legal fraction. Rounding down
    rather than to nearest matters: rounding up could exceed the budget the
    caller set.
    """

    def __init__(
        self, config: BacktestConfig, instrument: Instrument | None = None
    ) -> None:
        self._config = config
        # Defaults to the configured default instrument, matching the engine's
        # own fallback, so a sizer can still be built from a config alone.
        self._instrument = instrument or resolve_instrument(None)

    def target_size(self, *, equity: Decimal, price: Decimal) -> Decimal:
        """How large a fresh position should be, in the instrument's units."""
        zero = Decimal("0")
        if price <= 0:
            return zero

        config = self._config
        if config.sizing_mode is SizingMode.FIXED_QUANTITY:
            return max(self._to_step(config.fixed_quantity), zero)

        if config.sizing_mode is SizingMode.FIXED_VALUE:
            budget = config.fixed_value
        else:
            budget = equity * config.equity_percent / Decimal("100")

        return max(self._to_step(budget / price), zero)

    def _to_step(self, size: Decimal) -> Decimal:
        """Round DOWN to a whole multiple of the instrument's increment.

        For an equity (step 1) this is the old ``int(...)`` truncation exactly.
        For BTC (step 0.00000001) it keeps eight decimals, so a percent-of-
        equity run sizes a real fraction instead of truncating to zero.
        """
        step = self._instrument.quantity_step
        return (Decimal(size) // step) * step


class BacktestEngine:
    """Runs a strategy over historical candles."""

    def __init__(
        self,
        *,
        config: BacktestConfig | None = None,
        spread: SpreadModel | None = None,
        slippage: SlippageModel | None = None,
        fees: FeeCalculator | None = None,
        indicator_service: IndicatorService | None = None,
    ) -> None:
        self.config = config or BacktestConfig()
        # The same three cost models the live engine uses; passing None takes
        # them straight from settings, so a backtest charges what live trading
        # charges unless deliberately told otherwise.
        self._execution = ExecutionEngine(
            session=None,  # type: ignore[arg-type]  # nothing is persisted
            spread=spread,
            slippage=slippage,
            fees=fees,
        )
        self._indicators = indicator_service or IndicatorService()
        #: Both rebuilt per run, once the instrument is known.
        self._sizer: PositionSizer | None = None
        self._asset_class = AssetClass.STOCK

    # -- public API ------------------------------------------------------

    def run(
        self,
        *,
        strategy: Strategy,
        candles: list[Candle],
        symbol: str | None = None,
        exchange: str | None = None,
        interval: str = "1d",
    ) -> BacktestResult:
        """Run ``strategy`` over ``candles`` and report what happened."""
        # Fall back to the configured instrument rather than a hard-coded
        # ticker, so a backtest driven directly (not via the API) still
        # labels itself correctly after the platform is repointed.
        instrument = resolve_instrument(symbol or settings.TRADING_SYMBOL)
        symbol = instrument.symbol
        exchange = exchange or instrument.exchange
        # Sizing and charges both follow the instrument, so a BTC run sizes
        # fractionally and is charged the crypto schedule.
        self._sizer = PositionSizer(self.config, instrument)
        self._asset_class = instrument.asset_class

        strategy.reset()
        portfolio = BacktestPortfolio(initial_cash=self.config.initial_capital)

        if not candles:
            return self._summarise(
                strategy, portfolio, instrument, exchange, interval
            )

        indicators = self._precompute(strategy, candles, interval)
        warmup = strategy.warmup_bars()
        last_index = len(candles) - 1

        for index, candle in enumerate(candles):
            # Mark the account on every bar, so the equity curve -- and the
            # drawdown taken from it -- reflects the whole run, not only the
            # bars that happened to trade.
            portfolio.record_equity(
                index=index, timestamp=candle.timestamp, mark_price=candle.close
            )

            if index < warmup or index >= last_index:
                # The final bar has no "next open" to fill against, and the
                # closing sweep below handles it instead.
                continue

            decision = strategy.on_bar(
                self._context(index, candles, indicators, portfolio)
            )
            if not decision.signal.is_actionable:
                continue

            self._execute(
                decision=decision,
                index=index,
                candles=candles,
                portfolio=portfolio,
            )

        if self.config.close_at_end:
            self._close_out(candles, portfolio)

        return self._summarise(strategy, portfolio, instrument, exchange, interval)

    # -- internals -------------------------------------------------------

    def _precompute(
        self, strategy: Strategy, candles: list[Candle], interval: str
    ) -> dict[str, list[Decimal | None]]:
        """Compute the strategy's indicators once over the whole series.

        Values are aligned by timestamp back onto the candle index, so bar N's
        indicator sits at position N. Warm-up bars stay ``None`` rather than
        shifting everything left -- an off-by-one here would silently feed a
        strategy the wrong bar's value.
        """
        specs = strategy.required_indicators()
        if not specs:
            return {}

        results = self._indicators.calculate(
            candles=candles, specs=specs, interval=interval
        )

        position_of = {candle.timestamp: index for index, candle in enumerate(candles)}
        aligned: dict[str, list[Decimal | None]] = {}

        for result in results:
            for series in result.series:
                values: list[Decimal | None] = [None] * len(candles)
                for point in series.points:
                    index = position_of.get(point.timestamp)
                    if index is not None:
                        values[index] = point.value
                aligned[series.key] = values

        return aligned

    def _context(
        self,
        index: int,
        candles: list[Candle],
        indicators: dict[str, list[Decimal | None]],
        portfolio: BacktestPortfolio,
    ) -> StrategyContext:
        candle = candles[index]
        return StrategyContext(
            index=index,
            candle=candle,
            # History up to and including this bar. Nothing after it.
            candles=candles[: index + 1],
            position=portfolio.quantity,
            average_price=portfolio.average_price,
            cash=portfolio.cash,
            equity=portfolio.equity(candle.close),
            _indicators=indicators,
        )

    def _reference_price(self, index: int, candles: list[Candle]) -> Decimal:
        if self.config.fill_timing is FillTiming.CURRENT_CLOSE:
            return candles[index].close
        return candles[index + 1].open

    def _order_quantity(
        self, signal: Signal, portfolio: BacktestPortfolio, price: Decimal
    ) -> Decimal:
        """Shares needed to move from the current position to the target one.

        ``BUY`` from a short and ``SHORT`` from a long cross zero in a single
        order, exactly as the live engine allows, so the quantity covers the
        existing exposure *plus* the new position.
        """
        current = Decimal(portfolio.quantity)
        zero = Decimal("0")
        target = self._sizer.target_size(
            equity=portfolio.equity(price), price=price
        )

        if signal is Signal.BUY:
            return max(target - current, zero)
        if signal is Signal.SHORT:
            return max(target + current, zero)
        if signal is Signal.SELL:
            return max(current, zero)
        if signal is Signal.COVER:
            return max(-current, zero)
        return zero

    def _execute(
        self,
        *,
        decision: Decision,
        index: int,
        candles: list[Candle],
        portfolio: BacktestPortfolio,
    ) -> None:
        side = decision.signal.order_side
        if side is None:
            return

        reference_price = self._reference_price(index, candles)
        quantity = Decimal(
            decision.quantity
            if decision.quantity is not None
            else self._order_quantity(decision.signal, portfolio, reference_price)
        )
        if quantity <= 0:
            return

        self._settle(
            side=side,
            quantity=quantity,
            reference_price=reference_price,
            # The fill belongs to the bar it executes on, not the one that
            # produced the signal.
            index=index + 1,
            candle=candles[index + 1] if index + 1 < len(candles) else candles[index],
            portfolio=portfolio,
            reason=decision.reason,
        )

    def _close_out(
        self, candles: list[Candle], portfolio: BacktestPortfolio
    ) -> None:
        """Flatten on the last bar so the result is realized, not paper."""
        if portfolio.quantity == 0:
            return

        final = candles[-1]
        side = (
            OrderSide.SELL if portfolio.quantity > 0 else OrderSide.BUY_TO_COVER
        )
        self._settle(
            side=side,
            quantity=abs(portfolio.quantity),
            reference_price=final.close,
            index=len(candles) - 1,
            candle=final,
            portfolio=portfolio,
            reason="end of backtest",
        )

        # Re-mark the final bar now the position is flat, so the curve ends on
        # the realized figure rather than the pre-close-out one.
        if portfolio.equity_curve:
            portfolio.equity_curve.pop()
        portfolio.record_equity(
            index=len(candles) - 1,
            timestamp=final.timestamp,
            mark_price=final.close,
        )

    def _settle(
        self,
        *,
        side: OrderSide,
        quantity: Decimal,
        reference_price: Decimal,
        index: int,
        candle: Candle,
        portfolio: BacktestPortfolio,
        reason: str,
    ) -> None:
        fill = self._execution.price_fill(
            side=side,
            quantity=quantity,
            reference_price=reference_price,
            asset_class=self._asset_class,
        )
        try:
            portfolio.apply(
                fill, index=index, timestamp=candle.timestamp, reason=reason
            )
        except InsufficientCash as exc:
            # Record and carry on: a strategy that cannot afford its signal
            # should show up in the results, not abort the run.
            logger.debug("Backtest order rejected at bar %s: %s", index, exc)

    def _summarise(
        self,
        strategy: Strategy,
        portfolio: BacktestPortfolio,
        instrument: Instrument,
        exchange: str,
        interval: str,
    ) -> BacktestResult:
        return summarise(
            strategy=strategy.name,
            symbol=instrument.symbol,
            exchange=exchange,
            asset_class=instrument.asset_class.value,
            # Recorded, not enforced: the run is driven by the bars supplied.
            # A crypto result says "crypto", so nobody reads a Saturday bar as
            # an error.
            trading_calendar=calendar_for(instrument).name,
            interval=interval,
            initial_capital=self.config.initial_capital,
            trades=portfolio.trades,
            curve=portfolio.equity_curve,
            rejected_orders=portfolio.rejected_orders,
            final_position=portfolio.quantity,
        )
