"""Performance analytics.

Aggregates the trade history into a summary. All arithmetic happens in
PostgreSQL over ``NUMERIC`` columns, so the totals are exact rather than
accumulated in Python.

**What counts as a win.** Only a fill that *closed* something realizes P&L --
an opening fill has ``gross_pnl = 0`` and merely costs its charges. Counting
those as losses would drag the win rate down meaninglessly, so wins and losses
are judged over closing fills only (``closed_quantity > 0``).

**Net, not gross.** A trade is a win when its **net** P&L is positive, after
charges. Judging on gross would report wins that actually lost money once the
contract note was paid.
"""

from dataclasses import dataclass
from decimal import Decimal

from sqlalchemy import Select, case, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.trading import Order, Trade
from app.trading.pnl import to_money

ZERO = Decimal("0.00")


@dataclass(frozen=True)
class TradeExtreme:
    """The single best or worst closing trade."""

    trade_id: int
    side: str
    quantity: Decimal
    execution_price: Decimal
    gross_pnl: Decimal
    total_charges: Decimal
    net_pnl: Decimal
    created_at: object


@dataclass(frozen=True)
class PerformanceSummary:
    """Aggregate trading performance."""

    total_trades: int
    #: Fills that closed exposure; only these can win or lose.
    closing_trades: int
    winning_trades: int
    losing_trades: int
    breakeven_trades: int
    #: Winners as a percentage of closing trades. None when there are none.
    win_rate: Decimal | None

    total_gross_pnl: Decimal
    total_charges: Decimal
    total_net_pnl: Decimal

    average_win: Decimal | None
    average_loss: Decimal | None
    #: Gross profit divided by gross loss. None when nothing has lost yet.
    profit_factor: Decimal | None

    largest_winning_trade: TradeExtreme | None
    largest_losing_trade: TradeExtreme | None

    total_orders: int
    filled_orders: int
    rejected_orders: int


def _closing_trades() -> Select:
    return select(Trade).where(Trade.closed_quantity > 0)


class PerformanceAnalyzer:
    """Computes the performance summary from persisted trades."""

    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def summary(self) -> PerformanceSummary:
        totals = await self._totals()
        outcomes = await self._outcomes()
        best = await self._extreme(descending=True)
        worst = await self._extreme(descending=False)
        orders = await self._order_counts()

        closing = outcomes["closing"]
        wins = outcomes["wins"]

        win_rate = (
            (Decimal(wins) / Decimal(closing) * Decimal("100")).quantize(
                Decimal("0.01")
            )
            if closing
            else None
        )

        gross_profit = outcomes["gross_profit"]
        gross_loss = abs(outcomes["gross_loss"])
        profit_factor = (
            (gross_profit / gross_loss).quantize(Decimal("0.01"))
            if gross_loss > 0
            else None
        )

        return PerformanceSummary(
            total_trades=totals["count"],
            closing_trades=closing,
            winning_trades=wins,
            losing_trades=outcomes["losses"],
            breakeven_trades=closing - wins - outcomes["losses"],
            win_rate=win_rate,
            total_gross_pnl=totals["gross"],
            total_charges=totals["charges"],
            total_net_pnl=totals["net"],
            average_win=(
                to_money(gross_profit / Decimal(wins)) if wins else None
            ),
            average_loss=(
                to_money(outcomes["gross_loss"] / Decimal(outcomes["losses"]))
                if outcomes["losses"]
                else None
            ),
            profit_factor=profit_factor,
            largest_winning_trade=best,
            largest_losing_trade=worst,
            total_orders=orders["total"],
            filled_orders=orders["filled"],
            rejected_orders=orders["rejected"],
        )

    # -- aggregates ------------------------------------------------------

    async def _totals(self) -> dict:
        """Totals across *every* fill.

        Charges are summed over all fills, opening ones included -- entering a
        position costs money even though it realizes nothing.
        """
        row = (
            await self._session.execute(
                select(
                    func.count(Trade.id),
                    func.coalesce(func.sum(Trade.gross_pnl), 0),
                    func.coalesce(func.sum(Trade.total_charges), 0),
                    func.coalesce(func.sum(Trade.net_pnl), 0),
                )
            )
        ).one()

        return {
            "count": int(row[0]),
            "gross": to_money(Decimal(row[1])),
            "charges": to_money(Decimal(row[2])),
            "net": to_money(Decimal(row[3])),
        }

    async def _outcomes(self) -> dict:
        """Win/loss counts and sums over closing fills only."""
        row = (
            await self._session.execute(
                select(
                    func.count(Trade.id),
                    func.coalesce(
                        func.sum(case((Trade.net_pnl > 0, 1), else_=0)), 0
                    ),
                    func.coalesce(
                        func.sum(case((Trade.net_pnl < 0, 1), else_=0)), 0
                    ),
                    func.coalesce(
                        func.sum(case((Trade.net_pnl > 0, Trade.net_pnl), else_=0)), 0
                    ),
                    func.coalesce(
                        func.sum(case((Trade.net_pnl < 0, Trade.net_pnl), else_=0)), 0
                    ),
                ).where(Trade.closed_quantity > 0)
            )
        ).one()

        return {
            "closing": int(row[0]),
            "wins": int(row[1]),
            "losses": int(row[2]),
            "gross_profit": to_money(Decimal(row[3])),
            "gross_loss": to_money(Decimal(row[4])),
        }

    async def _extreme(self, *, descending: bool) -> TradeExtreme | None:
        """The best (or worst) closing trade by net P&L."""
        order_by = Trade.net_pnl.desc() if descending else Trade.net_pnl.asc()
        trade = (
            await self._session.execute(
                _closing_trades().order_by(order_by, Trade.id.asc()).limit(1)
            )
        ).scalar_one_or_none()

        if trade is None:
            return None

        # A "largest winner" that lost money, or a "largest loser" that made
        # money, would be misleading -- report nothing instead.
        if descending and trade.net_pnl <= 0:
            return None
        if not descending and trade.net_pnl >= 0:
            return None

        return TradeExtreme(
            trade_id=trade.id,
            side=str(trade.side),
            quantity=trade.quantity,
            execution_price=trade.execution_price,
            gross_pnl=trade.gross_pnl,
            total_charges=trade.total_charges,
            net_pnl=trade.net_pnl,
            created_at=trade.created_at,
        )

    async def _order_counts(self) -> dict:
        row = (
            await self._session.execute(
                select(
                    func.count(Order.id),
                    func.coalesce(
                        func.sum(case((Order.status == "FILLED", 1), else_=0)), 0
                    ),
                    func.coalesce(
                        func.sum(case((Order.status == "REJECTED", 1), else_=0)), 0
                    ),
                )
            )
        ).one()

        return {
            "total": int(row[0]),
            "filled": int(row[1]),
            "rejected": int(row[2]),
        }
