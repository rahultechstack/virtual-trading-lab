"""Backtest metrics.

Every metric here is computed from the **bars actually supplied**, never from a
calendar assumption. Nothing divides by 252 trading days, annualises against a
weekday count, or filters bars by weekday, so a 24/7 crypto series and a
Mon-Fri equity series are both measured correctly by the same code. The result
records which calendar the instrument trades under so a reader can tell them
apart.

The win/loss rules match the live ``PerformanceAnalyzer`` exactly, so a
backtest and a real account are measured the same way:

* **Only closing fills can win or lose.** An opening fill realizes nothing and
  merely costs its charges.
* **A win is judged on net, not gross.** A trade that made money before
  charges and lost after them is a loss.

Anything else would let a strategy look better in backtest than it could ever
be live, which is the whole failure mode this framework exists to avoid.
"""

from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal

from app.backtest.portfolio import BacktestTrade, EquityPoint
from app.trading.pnl import to_money

ZERO = Decimal("0.00")


@dataclass(frozen=True)
class DrawdownResult:
    """The worst peak-to-trough fall in account value."""

    max_drawdown: Decimal
    max_drawdown_pct: Decimal
    peak_value: Decimal
    trough_value: Decimal
    peak_at: datetime | None
    trough_at: datetime | None


@dataclass(frozen=True)
class BacktestResult:
    """Everything one backtest produced."""

    strategy: str
    symbol: str
    exchange: str
    #: Which asset class was backtested. A crypto run has NO weekday or session
    #: assumption anywhere in it -- see the module docstring.
    asset_class: str
    #: The market calendar the instrument trades under: "nse" or "crypto".
    trading_calendar: str
    interval: str

    start_at: datetime | None
    end_at: datetime | None
    bars: int

    initial_capital: Decimal
    final_equity: Decimal
    total_return: Decimal
    total_return_pct: Decimal

    total_trades: int
    closing_trades: int
    winning_trades: int
    losing_trades: int
    breakeven_trades: int
    win_rate: Decimal | None

    gross_pnl: Decimal
    total_charges: Decimal
    net_pnl: Decimal

    max_drawdown: Decimal
    max_drawdown_pct: Decimal
    profit_factor: Decimal | None
    average_win: Decimal | None
    average_loss: Decimal | None
    largest_win: Decimal | None
    largest_loss: Decimal | None

    #: Bars spent holding a position, as a percentage of the run.
    exposure_pct: Decimal
    rejected_orders: int
    final_position: Decimal

    trades: list[BacktestTrade]
    equity_curve: list[EquityPoint]


def max_drawdown(curve: list[EquityPoint]) -> DrawdownResult:
    """Worst peak-to-trough decline in total value.

    Walks the curve once, tracking the running high. The drawdown is measured
    from each peak forward, so a later, deeper fall from a lower peak does not
    displace an earlier, larger one measured in absolute terms.
    """
    if not curve:
        return DrawdownResult(ZERO, ZERO, ZERO, ZERO, None, None)

    peak = curve[0].total_value
    peak_at = curve[0].timestamp
    best_peak, best_trough = peak, peak
    best_peak_at, best_trough_at = peak_at, peak_at
    worst = ZERO

    for point in curve:
        if point.total_value > peak:
            peak = point.total_value
            peak_at = point.timestamp
            continue

        decline = peak - point.total_value
        if decline > worst:
            worst = decline
            best_peak, best_trough = peak, point.total_value
            best_peak_at, best_trough_at = peak_at, point.timestamp

    percent = (
        to_money(worst / best_peak * Decimal("100")) if best_peak > 0 else ZERO
    )

    return DrawdownResult(
        max_drawdown=to_money(worst),
        max_drawdown_pct=percent,
        peak_value=best_peak,
        trough_value=best_trough,
        peak_at=best_peak_at,
        trough_at=best_trough_at,
    )


def summarise(
    *,
    strategy: str,
    symbol: str,
    exchange: str,
    interval: str,
    initial_capital: Decimal,
    trades: list[BacktestTrade],
    curve: list[EquityPoint],
    rejected_orders: int,
    final_position: Decimal,
    asset_class: str = "STOCK",
    trading_calendar: str = "nse",
) -> BacktestResult:
    """Turn the raw run into the reported metrics."""
    closing = [trade for trade in trades if trade.is_closing]
    wins = [trade for trade in closing if trade.net_pnl > 0]
    losses = [trade for trade in closing if trade.net_pnl < 0]

    gross_profit = sum((trade.net_pnl for trade in wins), ZERO)
    gross_loss = sum((trade.net_pnl for trade in losses), ZERO)

    final_equity = curve[-1].total_value if curve else initial_capital
    total_return = to_money(final_equity - initial_capital)

    drawdown = max_drawdown(curve)
    exposed = sum(1 for point in curve if point.position != 0)

    return BacktestResult(
        strategy=strategy,
        symbol=symbol,
        exchange=exchange,
        asset_class=asset_class,
        trading_calendar=trading_calendar,
        interval=interval,
        start_at=curve[0].timestamp if curve else None,
        end_at=curve[-1].timestamp if curve else None,
        bars=len(curve),
        initial_capital=initial_capital,
        final_equity=final_equity,
        total_return=total_return,
        total_return_pct=(
            to_money(total_return / initial_capital * Decimal("100"))
            if initial_capital > 0
            else ZERO
        ),
        total_trades=len(trades),
        closing_trades=len(closing),
        winning_trades=len(wins),
        losing_trades=len(losses),
        breakeven_trades=len(closing) - len(wins) - len(losses),
        win_rate=(
            (Decimal(len(wins)) / Decimal(len(closing)) * Decimal("100")).quantize(
                Decimal("0.01")
            )
            if closing
            else None
        ),
        gross_pnl=to_money(sum((trade.gross_pnl for trade in trades), ZERO)),
        total_charges=to_money(sum((trade.total_charges for trade in trades), ZERO)),
        net_pnl=to_money(sum((trade.net_pnl for trade in trades), ZERO)),
        max_drawdown=drawdown.max_drawdown,
        max_drawdown_pct=drawdown.max_drawdown_pct,
        profit_factor=(
            (gross_profit / abs(gross_loss)).quantize(Decimal("0.01"))
            if gross_loss < 0
            else None
        ),
        average_win=to_money(gross_profit / Decimal(len(wins))) if wins else None,
        average_loss=to_money(gross_loss / Decimal(len(losses))) if losses else None,
        largest_win=max((trade.net_pnl for trade in wins), default=None),
        largest_loss=min((trade.net_pnl for trade in losses), default=None),
        exposure_pct=(
            to_money(Decimal(exposed) / Decimal(len(curve)) * Decimal("100"))
            if curve
            else ZERO
        ),
        rejected_orders=rejected_orders,
        final_position=final_position,
        trades=trades,
        equity_curve=curve,
    )
