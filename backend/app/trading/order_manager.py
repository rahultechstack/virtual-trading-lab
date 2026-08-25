"""Order lifecycle.

Creates order rows and moves them between states. It performs no accounting --
that belongs to the position and portfolio managers.
"""

from datetime import UTC, datetime
from decimal import Decimal

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.enums import OrderSide, OrderStatus, OrderType
from app.models.trading import Order


class OrderManager:
    """Persistence and state transitions for orders."""

    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def create(
        self,
        *,
        symbol: str,
        exchange: str,
        side: OrderSide,
        quantity: int,
        requested_price: Decimal | None,
        order_type: OrderType = OrderType.MARKET,
    ) -> Order:
        """Record a new order in ``PENDING``."""
        order = Order(
            symbol=symbol,
            exchange=exchange,
            side=side,
            order_type=order_type,
            quantity=quantity,
            requested_price=requested_price,
            status=OrderStatus.PENDING,
        )
        self._session.add(order)
        await self._session.flush()
        return order

    async def mark_filled(self, order: Order, execution_price: Decimal) -> Order:
        order.status = OrderStatus.FILLED
        order.execution_price = execution_price
        order.filled_at = datetime.now(tz=UTC)
        await self._session.flush()
        return order

    async def mark_rejected(self, order: Order, reason: str) -> Order:
        """Record why an order failed.

        Rejections are kept rather than discarded: the audit trail should show
        what was attempted, not only what succeeded.
        """
        order.status = OrderStatus.REJECTED
        order.rejection_reason = reason[:500]
        await self._session.flush()
        return order

    async def get(self, order_id: int) -> Order | None:
        result = await self._session.execute(select(Order).where(Order.id == order_id))
        return result.scalar_one_or_none()

    async def list_recent(
        self, *, limit: int = 100, offset: int = 0, status: OrderStatus | None = None
    ) -> list[Order]:
        """Newest first."""
        query = select(Order).order_by(Order.id.desc()).limit(limit).offset(offset)
        if status is not None:
            query = query.where(Order.status == status)
        result = await self._session.execute(query)
        return list(result.scalars().all())
