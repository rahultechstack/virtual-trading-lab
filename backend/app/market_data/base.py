"""The provider abstraction.

Everything above this line in the stack (services, API, and later the trading
engine) depends only on ``MarketDataProvider``. Vendor specifics — symbol
formats, endpoint shapes, auth — live in the implementations below it.
"""

from abc import ABC, abstractmethod
from collections.abc import AsyncIterator
from datetime import datetime

from app.core.exceptions import LiveDataNotSupportedError
from app.schemas.market_data import (
    Candle,
    Interval,
    ProviderCapabilities,
    Quote,
)


class MarketDataProvider(ABC):
    """Contract every market-data source must satisfy."""

    @property
    @abstractmethod
    def capabilities(self) -> ProviderCapabilities:
        """Declare honestly what this provider does and does not support."""

    @abstractmethod
    async def get_current_quote(self, symbol: str, exchange: str) -> Quote:
        """Return the latest quote.

        Raises:
            MarketDataUnavailableError: upstream failed or returned no data.
        """

    @abstractmethod
    async def get_historical_candles(
        self,
        symbol: str,
        exchange: str,
        interval: Interval,
        start: datetime | None = None,
        end: datetime | None = None,
        limit: int | None = None,
    ) -> list[Candle]:
        """Return OHLCV bars, oldest first.

        Raises:
            UnsupportedIntervalError: the provider does not serve ``interval``.
            MarketDataUnavailableError: upstream failed.
        """

    def subscribe_live_data(
        self, symbol: str, exchange: str
    ) -> AsyncIterator[Quote]:
        """Stream quotes as the provider pushes them.

        The default implementation refuses. A provider without a push feed must
        leave this alone rather than emulate streaming by polling — callers
        need to be able to tell the difference.

        Raises:
            LiveDataNotSupportedError: unless the provider overrides this.
        """
        raise LiveDataNotSupportedError(
            f"Provider '{self.capabilities.name}' has no live streaming feed. "
            "Poll get_current_quote() instead."
        )

    async def aclose(self) -> None:
        """Release any held resources. Safe to call more than once."""
