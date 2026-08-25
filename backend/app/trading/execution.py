"""Execution.

Turns an accepted order into a fill and records the resulting trade.

Stage 4 fills at the price the caller supplies, in full and immediately. There
is no slippage, no brokerage, no tax and no partial filling -- deliberately, so
the accounting can be verified against hand-worked examples. This class is the
single seam where a matching engine or a live-price feed will later plug in.
"""

from dataclasses import dataclass
from decimal import Decimal

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.enums import OrderSide
from app.models.trading import Order, Trade


@dataclass(frozen=True)
class Fill:
    """The outcome of executing an order."""

    quantity: int
    price: Decimal
    side: OrderSide

    @property
    def signed_quantity(self) -> int:
        """Positive when the fill increases the position, negative when it reduces it."""
        return self.quantity * self.side.direction

    @property
    def notional(self) -> Decimal:
        """Absolute cash value of the fill."""
        return self.price * Decimal(self.quantity)


class ExecutionEngine:
    """Executes orders and writes trade records."""

    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    @staticmethod
    def execute(order: Order, execution_price: Decimal) -> Fill:
        """Fill the order completely at the supplied price.

        Pure: it decides the fill but writes nothing. Persisting the result is
        ``record_trade``'s job, which keeps this method trivially testable.
        """
        return Fill(quantity=order.quantity, price=execution_price, side=order.side)

    async def record_trade(
        self,
        *,
        order: Order,
        fill: Fill,
        realized_pnl: Decimal,
        closed_quantity: int,
    ) -> Trade:
        """Persist the fill, with the P&L it locked in."""
        trade = Trade(
            order_id=order.id,
            symbol=order.symbol,
            exchange=order.exchange,
            side=fill.side,
            quantity=fill.quantity,
            execution_price=fill.price,
            realized_pnl=realized_pnl,
            closed_quantity=closed_quantity,
        )
        self._session.add(trade)
        await self._session.flush()
        return trade

    async def list_recent(self, *, limit: int = 100, offset: int = 0) -> list[Trade]:
        """Newest first."""
        result = await self._session.execute(
            select(Trade).order_by(Trade.id.desc()).limit(limit).offset(offset)
        )
        return list(result.scalars().all())
