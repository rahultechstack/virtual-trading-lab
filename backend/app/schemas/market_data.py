"""Market-data contracts.

Provider-neutral by design: nothing here mentions a specific vendor, so the
trading engine can be written against these models and the provider swapped
without touching it.
"""

from datetime import datetime
from decimal import Decimal
from enum import StrEnum

from pydantic import BaseModel, Field


class Interval(StrEnum):
    """Candle intervals the platform understands.

    A provider advertises the subset it actually serves through
    ``ProviderCapabilities.supported_intervals``.
    """

    ONE_MINUTE = "1m"
    FIVE_MINUTES = "5m"
    FIFTEEN_MINUTES = "15m"
    THIRTY_MINUTES = "30m"
    ONE_HOUR = "1h"
    ONE_DAY = "1d"
    ONE_WEEK = "1wk"
    ONE_MONTH = "1mo"


class Quote(BaseModel):
    """A point-in-time snapshot of the instrument."""

    symbol: str
    exchange: str

    last_price: Decimal = Field(description="Last traded price.")
    bid: Decimal | None = Field(
        default=None,
        description="Best bid. None when the provider does not expose depth.",
    )
    ask: Decimal | None = Field(
        default=None,
        description="Best ask. None when the provider does not expose depth.",
    )
    volume: int = Field(description="Cumulative traded volume for the session.")
    timestamp: datetime = Field(description="Exchange timestamp of the quote, in UTC.")

    # Context — optional because not every provider returns them.
    previous_close: Decimal | None = None
    day_open: Decimal | None = None
    day_high: Decimal | None = None
    day_low: Decimal | None = None
    currency: str = "INR"

    # Provenance. Surfaced so the caller can never mistake delayed or
    # partial data for a full real-time feed.
    provider: str
    is_delayed: bool = Field(
        description="True when the provider serves this quote on a delay."
    )
    is_mock: bool = Field(
        default=False,
        description="True when this price was simulated, not observed.",
    )


class Candle(BaseModel):
    """A single OHLCV bar. ``timestamp`` is the bar's opening time, in UTC."""

    timestamp: datetime
    open: Decimal
    high: Decimal
    low: Decimal
    close: Decimal
    volume: int


class CandleSeries(BaseModel):
    """An ordered run of candles, oldest first."""

    symbol: str
    exchange: str
    interval: Interval
    provider: str
    count: int
    candles: list[Candle]


class ProviderCapabilities(BaseModel):
    """What a provider can and cannot do.

    Exposed over the API so the limitations of the configured feed are
    discoverable at runtime rather than buried in documentation.
    """

    name: str
    supports_quotes: bool
    supports_historical: bool
    supports_bid_ask: bool = Field(
        description="False when the feed carries no order-book depth."
    )
    supports_live_stream: bool = Field(
        description="False when there is no push/WebSocket feed available."
    )
    is_delayed: bool
    quote_delay_minutes: int = Field(
        description="Nominal delay. 0 means the feed is served without one."
    )
    requires_credentials: bool
    is_mock: bool = Field(
        default=False,
        description="True when this provider invents data rather than observing it.",
    )
    supported_intervals: list[Interval]
    limitations: list[str] = Field(
        default_factory=list,
        description="Plain-language list of what this provider cannot do.",
    )
