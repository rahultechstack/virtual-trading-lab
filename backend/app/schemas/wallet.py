"""Wallet API contracts.

Monetary fields are ``Decimal``. Pydantic serialises them without binary
floating-point rounding, so amounts survive the round trip exactly.
"""

from datetime import datetime
from decimal import Decimal

from pydantic import BaseModel, ConfigDict, Field

#: Shared column limits — mirrors Numeric(18, 2) in the ORM model.
_MONEY = {"max_digits": 18, "decimal_places": 2}


class WalletResponse(BaseModel):
    """The virtual account as returned by every wallet endpoint."""

    model_config = ConfigDict(from_attributes=True)

    id: int
    currency: str
    initial_balance: Decimal = Field(description="Opening capital.")
    cash_balance: Decimal = Field(description="Currently available cash.")
    created_at: datetime
    updated_at: datetime


class WalletInitializeRequest(BaseModel):
    """Optional override of the configured opening capital."""

    initial_balance: Decimal | None = Field(
        default=None,
        gt=0,
        description="Opening capital. Defaults to WALLET_INITIAL_BALANCE.",
        **_MONEY,
    )


class WalletResetRequest(BaseModel):
    """Reset instruction.

    Omit ``initial_balance`` to restore the existing opening capital; supply it
    to re-open the account with a different amount.
    """

    initial_balance: Decimal | None = Field(
        default=None,
        gt=0,
        description="New opening capital. Omit to keep the current one.",
        **_MONEY,
    )
