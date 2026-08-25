"""Backtest engine tests.

The parity suite at the end is the important one: it runs the same order
sequence through the live database-backed engine and the in-memory
backtester and asserts the numbers are identical. That is what makes a
backtest comparable to real trading rather than merely similar to it.
"""

from datetime import UTC, datetime, timedelta
from decimal import Decimal

import pytest
from sqlalchemy import select

from app.backtest.engine import (
    BacktestConfig,
    BacktestEngine,
    FillTiming,
    PositionSizer,
    SizingMode,
)
from app.backtest.portfolio import (
    BacktestPortfolio,
    EquityPoint,
    InsufficientCash,
)
from app.backtest.results import max_drawdown, summarise
from app.models.enums import OrderSide
from app.models.trading import Position
from app.schemas.market_data import Candle
from app.services.wallet_service import WalletService
from app.strategies.base import Decision, Signal, Strategy, StrategyContext
from app.strategies.ma_crossover import MovingAverageCrossover
from app.trading.engine import TradingEngine
from app.trading.execution import ExecutionEngine
from app.trading.fees import FeeCalculator, Segment
from app.trading.slippage import SlippageModel
from app.trading.spread import SpreadModel

D = Decimal
START = datetime(2026, 1, 1, tzinfo=UTC)


def make_candles(closes: list[float], *, opens: list[float] | None = None) -> list[Candle]:
    """Candles with an explicit open, so fill timing can be pinned down."""
    return [
        Candle(
            timestamp=START + timedelta(days=index),
            open=D(str(opens[index] if opens else close)),
            high=D(str(max(close, opens[index] if opens else close) + 1)),
            low=D(str(min(close, opens[index] if opens else close) - 1)),
            close=D(str(close)),
            volume=10_000,
        )
        for index, close in enumerate(closes)
    ]


def frictionless_engine(config: BacktestConfig | None = None) -> BacktestEngine:
    """No spread, slippage or charges, so arithmetic is exact by hand."""
    return BacktestEngine(
        config=config or BacktestConfig(),
        spread=SpreadModel.disabled(),
        slippage=SlippageModel.disabled(),
        fees=FeeCalculator.disabled(),
    )


class ScriptedStrategy(Strategy):
    """Emits a fixed decision on named bars. Keeps engine tests deterministic."""

    name = "scripted"

    def __init__(self, script: dict[int, Signal]) -> None:
        self.script = script

    def required_indicators(self):
        return []

    def on_bar(self, context: StrategyContext) -> Decision:
        signal = self.script.get(context.index)
        if signal is None:
            return Decision.hold()
        return Decision(signal=signal, reason="scripted")


# ==========================================================================
# Position sizing
# ==========================================================================


def test_fixed_quantity_sizing():
    sizer = PositionSizer(
        BacktestConfig(sizing_mode=SizingMode.FIXED_QUANTITY, fixed_quantity=250)
    )

    assert sizer.target_size(equity=D("1000000"), price=D("100")) == 250


def test_fixed_value_sizing():
    """100,000 of budget at 250 a share is 400 shares."""
    sizer = PositionSizer(
        BacktestConfig(sizing_mode=SizingMode.FIXED_VALUE, fixed_value=D("100000"))
    )

    assert sizer.target_size(equity=D("1000000"), price=D("250")) == 400


def test_percent_of_equity_sizing():
    """95% of 1,000,000 at 100 a share is 9,500 shares."""
    sizer = PositionSizer(
        BacktestConfig(
            sizing_mode=SizingMode.PERCENT_OF_EQUITY, equity_percent=D("95")
        )
    )

    assert sizer.target_size(equity=D("1000000"), price=D("100")) == 9500


def test_sizing_rounds_down_so_the_order_is_affordable():
    sizer = PositionSizer(
        BacktestConfig(sizing_mode=SizingMode.FIXED_VALUE, fixed_value=D("1000"))
    )

    assert sizer.target_size(equity=D("1000000"), price=D("300")) == 3


def test_a_non_positive_price_sizes_to_nothing():
    sizer = PositionSizer(BacktestConfig())

    assert sizer.target_size(equity=D("1000000"), price=D("0")) == 0


# ==========================================================================
# Portfolio mechanics
# ==========================================================================


def fill_for(side: OrderSide, quantity: int, price: Decimal):
    engine = ExecutionEngine(
        session=None,  # type: ignore[arg-type]
        spread=SpreadModel.disabled(),
        slippage=SlippageModel.disabled(),
        fees=FeeCalculator.disabled(),
    )
    return engine.price_fill(side=side, quantity=quantity, reference_price=price)


def test_a_buy_debits_cash_and_opens_a_long():
    portfolio = BacktestPortfolio(initial_cash=D("100000"))

    portfolio.apply(
        fill_for(OrderSide.BUY, 100, D("500")), index=0, timestamp=START
    )

    assert portfolio.quantity == 100
    assert portfolio.average_price == D("500")
    assert portfolio.cash == D("50000.00")


def test_a_sell_credits_cash_and_realizes_pnl():
    portfolio = BacktestPortfolio(initial_cash=D("100000"))
    portfolio.apply(fill_for(OrderSide.BUY, 100, D("500")), index=0, timestamp=START)

    trade = portfolio.apply(
        fill_for(OrderSide.SELL, 100, D("550")), index=1, timestamp=START
    )

    assert portfolio.quantity == 0
    assert trade.gross_pnl == D("5000.00")
    assert portfolio.cash == D("105000.00")


def test_a_reversal_crosses_zero_in_one_order():
    """The same behaviour the live engine implements."""
    portfolio = BacktestPortfolio(initial_cash=D("1000000"))
    portfolio.apply(fill_for(OrderSide.BUY, 100, D("500")), index=0, timestamp=START)

    trade = portfolio.apply(
        fill_for(OrderSide.SHORT_SELL, 250, D("550")), index=1, timestamp=START
    )

    assert portfolio.quantity == -150
    assert portfolio.average_price == D("550")
    assert trade.gross_pnl == D("5000.00"), "only the closed 100 realized"
    assert trade.closed_quantity == 100


def test_an_unaffordable_order_is_refused_and_changes_nothing():
    portfolio = BacktestPortfolio(initial_cash=D("1000"))

    with pytest.raises(InsufficientCash):
        portfolio.apply(
            fill_for(OrderSide.BUY, 100, D("500")), index=0, timestamp=START
        )

    assert portfolio.quantity == 0
    assert portfolio.cash == D("1000")
    assert portfolio.trades == []
    assert portfolio.rejected_orders == 1


def test_charges_come_out_of_cash():
    portfolio = BacktestPortfolio(initial_cash=D("1000000"))
    engine = ExecutionEngine(
        session=None,  # type: ignore[arg-type]
        spread=SpreadModel.disabled(),
        slippage=SlippageModel.disabled(),
        fees=FeeCalculator(segment=Segment.INTRADAY),
    )
    fill = engine.price_fill(
        side=OrderSide.BUY, quantity=100, reference_price=D("1000")
    )

    portfolio.apply(fill, index=0, timestamp=START)

    assert fill.total_charges > 0
    assert portfolio.cash == D("1000000") - D("100000") - fill.total_charges
    assert portfolio.total_charges == fill.total_charges


def test_equity_marks_the_position_to_market():
    portfolio = BacktestPortfolio(initial_cash=D("100000"))
    portfolio.apply(fill_for(OrderSide.BUY, 100, D("500")), index=0, timestamp=START)

    assert portfolio.equity(D("600")) == D("110000.00")
    assert portfolio.unrealized_pnl(D("600")) == D("10000.00")


# ==========================================================================
# Drawdown
# ==========================================================================


def curve(values: list[str]) -> list[EquityPoint]:
    return [
        EquityPoint(
            index=index,
            timestamp=START + timedelta(days=index),
            mark_price=D("100"),
            cash=D(value),
            position=0,
            position_value=D("0"),
            total_value=D(value),
            realized_pnl=D("0"),
            unrealized_pnl=D("0"),
            net_pnl=D("0"),
        )
        for index, value in enumerate(values)
    ]


def test_drawdown_measures_peak_to_trough():
    """100 -> 120 -> 90: the fall is 30 from the 120 peak, 25%."""
    result = max_drawdown(curve(["100", "120", "90", "110"]))

    assert result.max_drawdown == D("30.00")
    assert result.max_drawdown_pct == D("25.00")
    assert result.peak_value == D("120")
    assert result.trough_value == D("90")


def test_a_curve_that_only_rises_has_no_drawdown():
    result = max_drawdown(curve(["100", "110", "120"]))

    assert result.max_drawdown == D("0.00")
    assert result.max_drawdown_pct == D("0.00")


def test_drawdown_keeps_the_worst_not_the_latest():
    """A 50 fall early beats a 10 fall later."""
    result = max_drawdown(curve(["100", "150", "100", "120", "110"]))

    assert result.max_drawdown == D("50.00")


def test_an_empty_curve_is_handled():
    result = max_drawdown([])

    assert result.max_drawdown == D("0.00")
    assert result.peak_at is None


# ==========================================================================
# Engine mechanics
# ==========================================================================


def test_a_signal_fills_at_the_next_bar_open_by_default():
    """The close that produced the signal was not tradable at that moment."""
    candles = make_candles([100.0, 100.0, 100.0], opens=[100.0, 100.0, 777.0])
    engine = frictionless_engine(
        BacktestConfig(
            sizing_mode=SizingMode.FIXED_QUANTITY,
            fixed_quantity=10,
            close_at_end=False,
        )
    )

    result = engine.run(
        strategy=ScriptedStrategy({1: Signal.BUY}), candles=candles
    )

    assert result.trades[0].reference_price == D("777"), "bar 2's open"


def test_current_close_timing_fills_on_the_signal_bar():
    candles = make_candles([100.0, 555.0, 100.0], opens=[100.0, 100.0, 777.0])
    engine = frictionless_engine(
        BacktestConfig(
            fill_timing=FillTiming.CURRENT_CLOSE,
            sizing_mode=SizingMode.FIXED_QUANTITY,
            fixed_quantity=10,
            close_at_end=False,
        )
    )

    result = engine.run(
        strategy=ScriptedStrategy({1: Signal.BUY}), candles=candles
    )

    assert result.trades[0].reference_price == D("555"), "bar 1's close"


def test_the_equity_curve_has_a_point_for_every_bar():
    candles = make_candles([100.0] * 20)
    engine = frictionless_engine()

    result = engine.run(strategy=ScriptedStrategy({}), candles=candles)

    assert result.bars == 20
    assert len(result.equity_curve) == 20


def test_a_strategy_that_never_trades_returns_its_capital():
    candles = make_candles([100.0, 110.0, 90.0, 105.0])
    engine = frictionless_engine()

    result = engine.run(strategy=ScriptedStrategy({}), candles=candles)

    assert result.total_trades == 0
    assert result.final_equity == result.initial_capital
    assert result.win_rate is None
    assert result.profit_factor is None


def test_an_empty_candle_series_is_handled():
    result = frictionless_engine().run(
        strategy=ScriptedStrategy({}), candles=[]
    )

    assert result.bars == 0
    assert result.total_trades == 0


def test_the_open_position_is_closed_on_the_last_bar():
    """Otherwise the result is dominated by profit that was never taken."""
    candles = make_candles([100.0] * 6)
    engine = frictionless_engine(
        BacktestConfig(
            sizing_mode=SizingMode.FIXED_QUANTITY, fixed_quantity=10, close_at_end=True
        )
    )

    result = engine.run(strategy=ScriptedStrategy({1: Signal.BUY}), candles=candles)

    assert result.final_position == 0
    assert result.trades[-1].reason == "end of backtest"


def test_close_at_end_can_be_turned_off():
    candles = make_candles([100.0] * 6)
    engine = frictionless_engine(
        BacktestConfig(
            sizing_mode=SizingMode.FIXED_QUANTITY,
            fixed_quantity=10,
            close_at_end=False,
        )
    )

    result = engine.run(strategy=ScriptedStrategy({1: Signal.BUY}), candles=candles)

    assert result.final_position == 10


def test_trade_net_pnl_reconciles_with_the_equity_change():
    """Every rupee of return must be explained by the trades."""
    candles = make_candles([100.0, 105.0, 110.0, 108.0, 115.0, 112.0])
    engine = frictionless_engine(
        BacktestConfig(sizing_mode=SizingMode.FIXED_QUANTITY, fixed_quantity=100)
    )

    result = engine.run(
        strategy=ScriptedStrategy({1: Signal.BUY, 3: Signal.SELL}), candles=candles
    )

    assert result.net_pnl == result.total_return


def test_the_run_is_reproducible():
    candles = make_candles([100 + (index % 13) * 2.0 for index in range(80)])
    strategy = MovingAverageCrossover(fast=5, slow=15)

    first = frictionless_engine().run(strategy=strategy, candles=candles)
    second = frictionless_engine().run(strategy=strategy, candles=candles)

    assert first.net_pnl == second.net_pnl
    assert first.total_trades == second.total_trades


def test_an_unaffordable_signal_is_counted_not_fatal():
    candles = make_candles([100.0] * 6)
    engine = frictionless_engine(
        BacktestConfig(
            initial_capital=D("100"),
            sizing_mode=SizingMode.FIXED_QUANTITY,
            fixed_quantity=1000,
            close_at_end=False,
        )
    )

    result = engine.run(strategy=ScriptedStrategy({1: Signal.BUY}), candles=candles)

    assert result.rejected_orders == 1
    assert result.total_trades == 0
    assert result.final_equity == D("100")


# ==========================================================================
# Metrics
# ==========================================================================


def test_only_closing_fills_can_win_or_lose():
    """An entry realizes nothing; counting it would distort the win rate."""
    candles = make_candles([100.0] * 6)
    engine = frictionless_engine(
        BacktestConfig(
            sizing_mode=SizingMode.FIXED_QUANTITY,
            fixed_quantity=10,
            close_at_end=False,
        )
    )

    result = engine.run(strategy=ScriptedStrategy({1: Signal.BUY}), candles=candles)

    assert result.total_trades == 1
    assert result.closing_trades == 0
    assert result.winning_trades == 0
    assert result.win_rate is None


def test_win_and_loss_counts_and_averages():
    """One 500 winner and one 300 loser on 100 shares."""
    candles = make_candles([100.0] * 3 + [105.0] * 3 + [100.0] * 3 + [97.0] * 3)
    engine = frictionless_engine(
        BacktestConfig(
            sizing_mode=SizingMode.FIXED_QUANTITY,
            fixed_quantity=100,
            close_at_end=False,
        )
    )

    result = engine.run(
        strategy=ScriptedStrategy(
            {1: Signal.BUY, 4: Signal.SELL, 7: Signal.BUY, 10: Signal.SELL}
        ),
        candles=candles,
    )

    assert result.closing_trades == 2
    assert result.winning_trades == 1
    assert result.losing_trades == 1
    assert result.win_rate == D("50.00")
    assert result.average_win == D("500.00")
    assert result.average_loss == D("-300.00")
    assert result.profit_factor == D("1.67")


def test_a_win_is_judged_after_charges():
    """A gross-positive trade that charges swallow is a loss.

    Fills land on bar 2's open (1000.00) and bar 4's open (1000.30), so the
    gross gain is 3.00 on ten shares -- less than the charges on both legs.
    """
    candles = make_candles(
        [1000.0] * 5, opens=[1000.0, 1000.0, 1000.0, 1000.0, 1000.3]
    )
    engine = BacktestEngine(
        config=BacktestConfig(
            sizing_mode=SizingMode.FIXED_QUANTITY,
            fixed_quantity=10,
            close_at_end=False,
        ),
        spread=SpreadModel.disabled(),
        slippage=SlippageModel.disabled(),
        fees=FeeCalculator(segment=Segment.INTRADAY),
    )

    result = engine.run(
        strategy=ScriptedStrategy({1: Signal.BUY, 3: Signal.SELL}), candles=candles
    )

    closing = [trade for trade in result.trades if trade.is_closing][0]
    assert closing.gross_pnl > 0
    assert closing.net_pnl < 0
    assert result.winning_trades == 0
    assert result.losing_trades == 1


def test_charges_include_opening_fills():
    candles = make_candles([1000.0] * 6)
    engine = BacktestEngine(
        config=BacktestConfig(
            sizing_mode=SizingMode.FIXED_QUANTITY,
            fixed_quantity=10,
            close_at_end=False,
        ),
        spread=SpreadModel.disabled(),
        slippage=SlippageModel.disabled(),
        fees=FeeCalculator(segment=Segment.INTRADAY),
    )

    result = engine.run(strategy=ScriptedStrategy({1: Signal.BUY}), candles=candles)

    assert result.total_charges > 0
    assert result.net_pnl < 0, "the entry cost its charges"


def test_summary_reports_every_required_metric():
    result = summarise(
        strategy="x",
        symbol="RELIANCE",
        exchange="NSE",
        interval="1d",
        initial_capital=D("1000"),
        trades=[],
        curve=curve(["1000", "900"]),
        rejected_orders=0,
        final_position=0,
    )

    for field in (
        "total_trades",
        "winning_trades",
        "losing_trades",
        "win_rate",
        "gross_pnl",
        "total_charges",
        "net_pnl",
        "max_drawdown",
        "profit_factor",
        "average_win",
        "average_loss",
    ):
        assert hasattr(result, field), f"missing required metric: {field}"


# ==========================================================================
# Parity with the live trading engine
# ==========================================================================

SEQUENCE = [
    (OrderSide.BUY, 100, "1000"),
    (OrderSide.BUY, 50, "1010"),
    (OrderSide.SELL, 30, "1050"),
    (OrderSide.SELL, 120, "1080"),
    (OrderSide.SHORT_SELL, 80, "1100"),
    (OrderSide.BUY_TO_COVER, 80, "1040"),
]


def _cost_models():
    """Identical models on both sides, so only the plumbing differs."""
    return {
        "spread": SpreadModel(basis_points=D("20")),
        "slippage": SlippageModel(basis_points=D("10")),
        "fees": FeeCalculator(segment=Segment.INTRADAY),
    }


async def test_the_backtester_and_the_live_engine_agree_exactly(session):
    """The claim this whole stage rests on.

    The same orders at the same prices are run through the live,
    database-backed engine and through the in-memory backtest portfolio. Cash,
    position, average price, realized P&L and charges must match to the paisa.
    """
    models = _cost_models()

    # --- live path -------------------------------------------------------
    await WalletService(session).initialize_wallet(D("1000000.00"))
    live = TradingEngine(
        session, execution=ExecutionEngine(session, **models)
    )
    for side, quantity, price in SEQUENCE:
        await live.place_order(
            side=side, quantity=quantity, reference_price=D(price)
        )

    live_position = (await session.execute(select(Position))).scalar_one()
    live_portfolio = await live.get_portfolio()

    # --- backtest path ---------------------------------------------------
    execution = ExecutionEngine(session=None, **models)  # type: ignore[arg-type]
    book = BacktestPortfolio(initial_cash=D("1000000.00"))
    for index, (side, quantity, price) in enumerate(SEQUENCE):
        book.apply(
            execution.price_fill(
                side=side, quantity=quantity, reference_price=D(price)
            ),
            index=index,
            timestamp=START,
        )

    # --- they must agree -------------------------------------------------
    assert book.quantity == live_position.quantity
    assert book.average_price == live_position.average_price
    assert book.realized_pnl == live_position.realized_pnl
    assert book.total_charges == live_position.total_charges
    assert book.net_realized_pnl == live_position.net_realized_pnl
    assert book.cash == live_portfolio.cash_balance


async def test_parity_holds_for_the_fill_prices_too(session):
    """Not just the totals -- every individual fill must price identically."""
    models = _cost_models()
    await WalletService(session).initialize_wallet(D("1000000.00"))
    live = TradingEngine(session, execution=ExecutionEngine(session, **models))
    execution = ExecutionEngine(session=None, **models)  # type: ignore[arg-type]

    for side, quantity, price in SEQUENCE:
        live_result = await live.place_order(
            side=side, quantity=quantity, reference_price=D(price)
        )
        backtest_fill = execution.price_fill(
            side=side, quantity=quantity, reference_price=D(price)
        )

        assert backtest_fill.price == live_result.trade.execution_price
        assert backtest_fill.total_charges == live_result.total_charges
        assert backtest_fill.spread_cost == live_result.trade.spread_cost
        assert backtest_fill.slippage_cost == live_result.trade.slippage_cost
