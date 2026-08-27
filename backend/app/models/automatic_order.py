"""Automatic orders: stop-losses and custom price triggers.

An automatic order is a *standing instruction* — it sits ACTIVE until the market
price satisfies its condition, at which point the monitor claims it and hands
the execution to the ordinary ``TradingEngine``. There is no second execution
path: a triggered automatic order becomes a normal ``Order`` and ``Trade`` row
like any other.

**Statuses.** ``ACTIVE`` -> ``TRIGGERED`` on a successful fire, ``CANCELLED``
when the user cancels or the position it protected disappears, ``FAILED`` when
the engine rejected the resulting order. ``EXPIRED`` from the brief is *not*
implemented: nothing in this platform carries session or good-till-date
semantics, so an order would never reach it.

**Reuse.** ``action`` deliberately reuses the existing ``order_side`` enum, so a
trigger's action is exactly the side the engine will be asked to execute.
"""

from datetime import datetime
from decimal import Decimal
from enum import StrEnum

from sqlalchemy import (
    BigInteger,
    CheckConstraint,
    DateTime,
    Enum,
    ForeignKey,
    Index,
    Numeric,
    String,
)
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base, TimestampMixin
from app.market_data.instruments import AssetClass
from app.models.enums import OrderSide
from app.models.trading import MAX_ORDER_QUANTITY, QUANTITY

#: Prices and cash amounts, as everywhere else in the schema.
MONEY = Numeric(18, 2)


class AutomaticOrderType(StrEnum):
    """Why the order exists.

    The two differ in validation, not in execution: a ``STOP_LOSS`` is checked
    against the open position at creation time, a ``PRICE_TRIGGER`` is not.
    """

    STOP_LOSS = "STOP_LOSS"
    PRICE_TRIGGER = "PRICE_TRIGGER"


class TriggerCondition(StrEnum):
    """How the market price is compared to ``trigger_price``."""

    #: Fires when market price >= trigger price.
    GTE = "GTE"
    #: Fires when market price <= trigger price.
    LTE = "LTE"


class AutomaticOrderStatus(StrEnum):
    ACTIVE = "ACTIVE"
    TRIGGERED = "TRIGGERED"
    CANCELLED = "CANCELLED"
    #: Claimed and attempted, but the engine rejected the order. Terminal --
    #: it is never retried, so a doomed trigger cannot spin every tick.
    FAILED = "FAILED"


#: Statuses a user may no longer act on.
TERMINAL_STATUSES = frozenset(
    {
        AutomaticOrderStatus.TRIGGERED,
        AutomaticOrderStatus.CANCELLED,
        AutomaticOrderStatus.FAILED,
    }
)


class AutomaticOrder(TimestampMixin, Base):
    """A standing instruction to trade when the price reaches a level."""

    __tablename__ = "automatic_orders"
    __table_args__ = (
        CheckConstraint("quantity > 0", name="quantity_positive"),
        CheckConstraint(
            f"quantity <= {MAX_ORDER_QUANTITY}", name="quantity_within_bounds"
        ),
        CheckConstraint("trigger_price > 0", name="trigger_price_positive"),
        # A fired order must record when it fired.
        CheckConstraint(
            "status <> 'TRIGGERED' OR triggered_at IS NOT NULL",
            name="triggered_orders_have_a_timestamp",
        ),
        CheckConstraint(
            "status <> 'CANCELLED' OR cancelled_at IS NOT NULL",
            name="cancelled_orders_have_a_timestamp",
        ),
        # The monitor scans by (symbol, status) on every tick.
        Index("ix_automatic_orders_symbol_status", "symbol", "status"),
        Index("ix_automatic_orders_created_at", "created_at"),
    )

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)

    symbol: Mapped[str] = mapped_column(String(32), nullable=False, index=True)
    exchange: Mapped[str] = mapped_column(String(16), nullable=False, default="NSE")
    #: Which asset class this trigger belongs to. A crypto trigger stays armed
    #: around the clock; an equity one is only ever reached while its feed is
    #: being polled.
    asset_class: Mapped[AssetClass] = mapped_column(
        Enum(AssetClass, name="asset_class", native_enum=True, validate_strings=True),
        nullable=False,
        default=AssetClass.STOCK,
        index=True,
    )

    order_type: Mapped[AutomaticOrderType] = mapped_column(
        Enum(AutomaticOrderType, name="automatic_order_type", native_enum=True),
        nullable=False,
    )

    #: The level the market price is compared against.
    trigger_price: Mapped[Decimal] = mapped_column(MONEY, nullable=False)
    trigger_condition: Mapped[TriggerCondition] = mapped_column(
        Enum(TriggerCondition, name="trigger_condition", native_enum=True),
        nullable=False,
    )

    #: The side the engine executes when this fires. Same enum as Order.side.
    action: Mapped[OrderSide] = mapped_column(
        Enum(OrderSide, name="order_side", native_enum=True), nullable=False
    )
    quantity: Mapped[Decimal] = mapped_column(QUANTITY, nullable=False)

    status: Mapped[AutomaticOrderStatus] = mapped_column(
        Enum(AutomaticOrderStatus, name="automatic_order_status", native_enum=True),
        nullable=False,
        default=AutomaticOrderStatus.ACTIVE,
        index=True,
    )

    triggered_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    cancelled_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )

    #: The market price that satisfied the condition. Kept because the fill
    #: price differs from it once spread and slippage are applied.
    trigger_market_price: Mapped[Decimal | None] = mapped_column(MONEY, nullable=True)

    #: The order this produced, once it fired. SET NULL rather than CASCADE:
    #: deleting an order should not erase the record that a trigger fired.
    triggered_order_id: Mapped[int | None] = mapped_column(
        ForeignKey("orders.id", ondelete="SET NULL"), nullable=True, index=True
    )

    #: Why it was cancelled or why execution failed. Never set while ACTIVE.
    reason: Mapped[str | None] = mapped_column(String(500), nullable=True)

    @property
    def is_active(self) -> bool:
        return self.status is AutomaticOrderStatus.ACTIVE

    @property
    def is_stop_loss(self) -> bool:
        return self.order_type is AutomaticOrderType.STOP_LOSS

    def __repr__(self) -> str:  # pragma: no cover - debugging aid
        return (
            f"<AutomaticOrder id={self.id} {self.order_type} "
            f"{self.trigger_condition} {self.trigger_price} -> {self.action} "
            f"{self.quantity} status={self.status}>"
        )
