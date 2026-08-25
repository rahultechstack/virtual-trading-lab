"""Wallet ORM model.

The platform has exactly one virtual account, so the table is constrained to a
single row at the database level rather than by convention alone.
"""

from decimal import Decimal
from typing import Final

from sqlalchemy import CheckConstraint, Integer, Numeric, String
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base, TimestampMixin

#: Primary key of the one and only wallet row.
WALLET_ID: Final[int] = 1

#: Money precision: 16 digits before the decimal point, 2 after.
MONEY = Numeric(18, 2)


class Wallet(Base, TimestampMixin):
    """The single virtual trading account.

    ``initial_balance`` is the opening capital and is the value ``cash_balance``
    is restored to on reset. ``cash_balance`` is the currently available cash.
    In Stage 2 the two only diverge through an explicit reset; order execution
    arrives in a later stage.
    """

    __tablename__ = "wallet"
    __table_args__ = (
        # Hard singleton guarantee — a second wallet cannot be inserted.
        CheckConstraint("id = 1", name="singleton"),
        CheckConstraint("initial_balance > 0", name="initial_balance_positive"),
        CheckConstraint("cash_balance >= 0", name="cash_balance_non_negative"),
    )

    id: Mapped[int] = mapped_column(
        Integer, primary_key=True, autoincrement=False, default=WALLET_ID
    )

    currency: Mapped[str] = mapped_column(String(3), nullable=False, default="INR")

    # Decimal, never float: binary floating point cannot represent currency
    # amounts exactly and rounding errors compound across trades.
    initial_balance: Mapped[Decimal] = mapped_column(MONEY, nullable=False)
    cash_balance: Mapped[Decimal] = mapped_column(MONEY, nullable=False)

    def __repr__(self) -> str:  # pragma: no cover - debugging aid
        return (
            f"<Wallet id={self.id} cash={self.cash_balance} "
            f"initial={self.initial_balance} {self.currency}>"
        )
