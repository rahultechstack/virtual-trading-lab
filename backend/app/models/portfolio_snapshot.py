"""Portfolio snapshots.

A point-in-time record of what the account was worth. Together the rows form
the equity curve, which is the only way to see performance *over time* --
`positions` and `wallet` hold the present state and nothing else.

Snapshots are append-only history. Nothing updates a row once written; a
correction would be a new snapshot, not an edit.
"""

from datetime import datetime
from decimal import Decimal
from enum import StrEnum

from sqlalchemy import BigInteger, CheckConstraint, DateTime, Enum, Index, Integer, Numeric, String, func
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base

MONEY = Numeric(18, 2)
AVERAGE = Numeric(18, 4)


class SnapshotSource(StrEnum):
    """Why a snapshot was taken.

    Distinguishing them matters: the equity curve should be readable as a
    regular time series (``PERIODIC``) while still carrying an exact point at
    every moment the account actually changed (``TRADE``).
    """

    PERIODIC = "PERIODIC"
    TRADE = "TRADE"
    MANUAL = "MANUAL"


class PortfolioSnapshot(Base):
    """What the account was worth at one instant."""

    __tablename__ = "portfolio_snapshots"
    __table_args__ = (
        CheckConstraint("cash >= 0", name="cash_non_negative"),
        CheckConstraint(
            "mark_price IS NULL OR mark_price > 0", name="mark_price_positive"
        ),
        # The equity curve is always read newest-first or over a window.
        Index("ix_portfolio_snapshots_captured_at", "captured_at"),
    )

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)

    captured_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    source: Mapped[SnapshotSource] = mapped_column(
        Enum(SnapshotSource, name="snapshot_source", native_enum=True),
        nullable=False,
        default=SnapshotSource.PERIODIC,
        index=True,
    )

    #: The instrument, when exactly one position is open. NULL for a
    #: portfolio holding none or several -- no single symbol describes it.
    symbol: Mapped[str | None] = mapped_column(String(32), nullable=True)

    #: Signed position at the time: > 0 long, 0 flat, < 0 short.
    quantity: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    average_price: Mapped[Decimal] = mapped_column(
        AVERAGE, nullable=False, default=Decimal("0.0000")
    )
    #: Price the position was valued at. NULL when flat -- nothing to value.
    mark_price: Mapped[Decimal | None] = mapped_column(MONEY, nullable=True)

    cash: Mapped[Decimal] = mapped_column(MONEY, nullable=False)
    #: Signed market value of the open position; negative for a short.
    position_value: Mapped[Decimal] = mapped_column(
        MONEY, nullable=False, default=Decimal("0.00")
    )
    #: cash + position_value. The equity curve is drawn from this.
    total_value: Mapped[Decimal] = mapped_column(MONEY, nullable=False)

    #: Cumulative realized P&L from price movement, before charges.
    realized_pnl: Mapped[Decimal] = mapped_column(
        MONEY, nullable=False, default=Decimal("0.00")
    )
    #: Cumulative charges paid across every fill.
    total_charges: Mapped[Decimal] = mapped_column(
        MONEY, nullable=False, default=Decimal("0.00")
    )
    unrealized_pnl: Mapped[Decimal] = mapped_column(
        MONEY, nullable=False, default=Decimal("0.00")
    )
    #: Net realized plus unrealized -- P&L after every cost.
    net_pnl: Mapped[Decimal] = mapped_column(
        MONEY, nullable=False, default=Decimal("0.00")
    )

    def __repr__(self) -> str:  # pragma: no cover - debugging aid
        return (
            f"<PortfolioSnapshot {self.captured_at:%Y-%m-%d %H:%M} "
            f"total={self.total_value} net={self.net_pnl} src={self.source}>"
        )

    def is_equivalent_to(self, other: "PortfolioSnapshot | None") -> bool:
        """Whether this records the same account state as ``other``.

        Used to suppress duplicate periodic rows while the account sits idle,
        so the table does not fill with identical entries overnight.
        """
        if other is None:
            return False
        return (
            self.quantity == other.quantity
            and self.cash == other.cash
            and self.position_value == other.position_value
            and self.total_value == other.total_value
            and self.realized_pnl == other.realized_pnl
            and self.unrealized_pnl == other.unrealized_pnl
            and self.total_charges == other.total_charges
        )
