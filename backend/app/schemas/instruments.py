"""Instrument API contracts."""

from pydantic import BaseModel, ConfigDict, Field

from app.market_data.instruments import InstrumentType


class InstrumentResponse(BaseModel):
    """One tradable instrument.

    ``data_available`` reports whether the configured provider can actually
    serve this symbol. It is ``None`` when that has not been probed yet --
    probing costs an upstream call, so it is done on demand rather than for
    every row of a listing.
    """

    model_config = ConfigDict(from_attributes=True)

    symbol: str
    company_name: str
    exchange: str
    instrument_type: InstrumentType
    data_available: bool | None = Field(
        default=None,
        description="True/False once verified against the provider; null if unprobed.",
    )
