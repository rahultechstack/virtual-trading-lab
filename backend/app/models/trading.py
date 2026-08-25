"""Orders, trades and positions.

Money precision:

* ``Numeric(18, 2)`` for prices and P&L -- exchange prices and cash are
  two-decimal quantities.
* ``Numeric(18, 4)`` for ``Position.average_price`` -- it is a *derived*
  weighted average, so it keeps two extra digits to stop rounding drift
  accumulating across many partial fills.
"""

from datetime import datetime
from decimal import Decimal

from sqlalchemy import (
    BigInteger,
    CheckConstraint,
    DateTime,
    Enum,
    ForeignKey,
    Index,
    Integer,
    Numeric,
    String,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base, TimestampMixin
from app.models.enums import OrderSide, OrderStatus, OrderType

#: Prices and cash amounts.
MONEY = Numeric(18, 2)
#: Derived averages, carried at higher precision.
AVERAGE = Numeric(18, 4)

#: Sanity bound; a paper account has no business ordering more than this.
MAX_ORDER_QUANTITY = 10_000_000


def _side_enum(name: str) -> Enum:
    return Enum(OrderSide, name=name, native_enum=True, validate_strings=True)


class Order(TimestampMixin, Base):
    """An instruction to trade.

    Rejected orders are persisted too, so the audit trail shows what was
    attempted and why it failed -- not only what succeeded.
    """

    __tablename__ = "orders"
    __table_args__ = (
        CheckConstraint("quantity > 0", name="quantity_positive"),
        CheckConstraint(
            f"quantity <= {MAX_ORDER_QUANTITY}", name="quantity_within_bounds"
        ),
        CheckConstraint(
            "requested_price IS NULL OR requested_price > 0",
            name="requested_price_positive",
        ),
        CheckConstraint(
            "execution_price IS NULL OR execution_price > 0",
            name="execution_price_positive",
        ),
        # A filled order must record what it filled at.
        CheckConstraint(
            "status <> 'FILLED' OR execution_price IS NOT NULL",
            name="filled_orders_have_a_price",
        ),
        Index("ix_orders_created_at", "created_at"),
    )

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)

    symbol: Mapped[str] = mapped_column(String(32), nullable=False, index=True)
    exchange: Mapped[str] = mapped_column(String(16), nullable=False, default="NSE")

    side: Mapped[OrderSide] = mapped_column(_side_enum("order_side"), nullable=False)
    order_type: Mapped[OrderType] = mapped_column(
        Enum(OrderType, name="order_type", native_enum=True),
        nullable=False,
        default=OrderType.MARKET,
    )

    quantity: Mapped[int] = mapped_column(Integer, nullable=False)

    #: What the caller asked for. Informational in Stage 4.
    requested_price: Mapped[Decimal | None] = mapped_column(MONEY, nullable=True)
    #: What it actually filled at. NULL until filled.
    execution_price: Mapped[Decimal | None] = mapped_column(MONEY, nullable=True)

    status: Mapped[OrderStatus] = mapped_column(
        Enum(OrderStatus, name="order_status", native_enum=True),
        nullable=False,
        default=OrderStatus.PENDING,
        index=True,
    )
    rejection_reason: Mapped[str | None] = mapped_column(String(500), nullable=True)
    filled_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )

    trades: Mapped[list["Trade"]] = relationship(
        back_populates="order", cascade="all, delete-orphan", lazy="selectin"
    )

    @property
    def signed_quantity(self) -> int:
        """Quantity with the sign the side implies."""
        return self.quantity * self.side.direction

    def __repr__(self) -> str:  # pragma: no cover - debugging aid
        return (
            f"<Order id={self.id} {self.side} {self.quantity} "
            f"{self.symbol} status={self.status}>"
        )


class Trade(TimestampMixin, Base):
    """A fill. One per filled order in Stage 4 (no partial fills yet)."""

    __tablename__ = "trades"
    __table_args__ = (
        CheckConstraint("quantity > 0", name="quantity_positive"),
        CheckConstraint("execution_price > 0", name="execution_price_positive"),
        Index("ix_trades_created_at", "created_at"),
    )

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)

    order_id: Mapped[int] = mapped_column(
        ForeignKey("orders.id", ondelete="CASCADE"), nullable=False, index=True
    )

    symbol: Mapped[str] = mapped_column(String(32), nullable=False, index=True)
    exchange: Mapped[str] = mapped_column(String(16), nullable=False, default="NSE")

    side: Mapped[OrderSide] = mapped_column(_side_enum("order_side"), nullable=False)
    quantity: Mapped[int] = mapped_column(Integer, nullable=False)
    execution_price: Mapped[Decimal] = mapped_column(MONEY, nullable=False)

    #: P&L this fill locked in. Zero for a fill that only opens or adds to a
    #: position; non-zero only where it closed one. May be negative.
    realized_pnl: Mapped[Decimal] = mapped_column(
        MONEY, nullable=False, default=Decimal("0.00")
    )

    #: How much of the fill closed an existing position, for auditability.
    closed_quantity: Mapped[int] = mapped_column(Integer, nullable=False, default=0)

    order: Mapped[Order] = relationship(back_populates="trades")

    @property
    def signed_quantity(self) -> int:
        return self.quantity * self.side.direction

    def __repr__(self) -> str:  # pragma: no cover - debugging aid
        return (
            f"<Trade id={self.id} order={self.order_id} {self.side} "
            f"{self.quantity}@{self.execution_price} pnl={self.realized_pnl}>"
        )


class Position(TimestampMixin, Base):
    """The net holding in one instrument.

    ``quantity`` carries the direction:

    * ``> 0`` -- long
    * ``= 0`` -- flat
    * ``< 0`` -- short

    ``average_price`` is the weighted average entry price of the *open*
    quantity and is always positive; it resets to zero when the position goes
    flat. ``realized_pnl`` accumulates across the position's whole history and
    survives going flat.
    """

    __tablename__ = "positions"
    __table_args__ = (
        CheckConstraint("average_price >= 0", name="average_price_non_negative"),
        # A flat position cannot carry an entry price, and an open one must.
        CheckConstraint(
            "(quantity = 0 AND average_price = 0) OR "
            "(quantity <> 0 AND average_price > 0)",
            name="average_price_matches_quantity",
        ),
    )

    #: Natural key -- one row per instrument, and this platform trades one.
    symbol: Mapped[str] = mapped_column(String(32), primary_key=True)
    exchange: Mapped[str] = mapped_column(String(16), nullable=False, default="NSE")

    quantity: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    average_price: Mapped[Decimal] = mapped_column(
        AVERAGE, nullable=False, default=Decimal("0.0000")
    )
    realized_pnl: Mapped[Decimal] = mapped_column(
        MONEY, nullable=False, default=Decimal("0.00")
    )

    @property
    def is_long(self) -> bool:
        return self.quantity > 0

    @property
    def is_short(self) -> bool:
        return self.quantity < 0

    @property
    def is_flat(self) -> bool:
        return self.quantity == 0

    def __repr__(self) -> str:  # pragma: no cover - debugging aid
        return (
            f"<Position {self.symbol} qty={self.quantity} "
            f"avg={self.average_price} realized={self.realized_pnl}>"
        )
