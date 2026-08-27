"""Instrument API contracts."""

from decimal import Decimal

from pydantic import BaseModel, ConfigDict, Field, computed_field, field_serializer

from app.market_data.instruments import AssetClass, InstrumentType


class InstrumentResponse(BaseModel):
    """One tradable instrument.

    Carries everything a client needs to render and trade it without knowing
    anything about asset classes itself: which market it belongs to, when that
    market trades, and what sizes are legal.

    ``data_available`` reports whether the provider routed for this asset class
    can actually serve the symbol. It is ``None`` when that has not been probed
    yet -- probing costs an upstream call, so it is done on demand rather than
    for every row of a listing.
    """

    model_config = ConfigDict(from_attributes=True)

    symbol: str
    company_name: str = Field(
        description="Company name for a stock, asset name for a coin."
    )
    asset_class: AssetClass = Field(description="STOCK or CRYPTO.")
    exchange: str = Field(description='Venue code: "NSE", or "CRYPTO" for coins.')
    market: str = Field(description='Human label, e.g. "NSE Cash Market".')
    trading_hours: str = Field(
        description='Human label, e.g. "09:15-15:30 IST, Mon-Fri" or "24/7".'
    )
    instrument_type: InstrumentType = Field(description="EQUITY or CRYPTOCURRENCY.")
    quantity_step: Decimal = Field(
        description=(
            "Smallest tradable increment. 1 for a stock, 0.00000001 for crypto. "
            "An order size must be a whole multiple of this."
        )
    )
    data_available: bool | None = Field(
        default=None,
        description="True/False once verified against the provider; null if unprobed.",
    )

    @field_serializer("quantity_step")
    def _plain_step(self, value: Decimal) -> str:
        """Serialise as plain decimal, never scientific notation.

        ``Decimal("0.00000001")`` renders as ``1E-8`` by default, which is
        unreadable in a listing and awkward as an HTML input ``step``. ``f``
        formatting gives ``0.00000001``.
        """
        return f"{value:f}"

    @computed_field
    @property
    def is_fractional(self) -> bool:
        """Whether fractional sizes are allowed. Drives the quantity input."""
        return self.quantity_step < 1

    @computed_field
    @property
    def quantity_precision(self) -> int:
        """Decimal places implied by ``quantity_step``."""
        exponent = self.quantity_step.normalize().as_tuple().exponent
        return max(0, -int(exponent))
