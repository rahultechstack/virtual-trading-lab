"""Market-data service for the single configured instrument.

Sits between the API and whatever provider is configured. It owns the rules
that are true of *this platform* rather than of any feed:

* exactly one tradable instrument, set by TRADING_SYMBOL / TRADING_EXCHANGE;
* the interval requested must be one the configured provider actually serves;
* results are wrapped in the platform's own response models.

It depends only on ``MarketDataProvider``, never on a concrete vendor.
"""

from datetime import datetime

from app.core.config import settings
from app.core.exceptions import UnsupportedIntervalError, UnsupportedSymbolError
from app.core.logging import get_logger
from app.market_data.base import MarketDataProvider
from app.schemas.market_data import (
    CandleSeries,
    Interval,
    ProviderCapabilities,
    Quote,
)

logger = get_logger(__name__)

#: Upper bound on candles returned in one response.
MAX_CANDLES = 5000


class RelianceMarketDataService:
    """Market data for the single supported instrument."""

    def __init__(self, provider: MarketDataProvider) -> None:
        self._provider = provider

    @property
    def symbol(self) -> str:
        return settings.TRADING_SYMBOL

    @property
    def exchange(self) -> str:
        return settings.TRADING_EXCHANGE

    @property
    def capabilities(self) -> ProviderCapabilities:
        """What the configured feed can actually do."""
        return self._provider.capabilities

    # -- validation ------------------------------------------------------

    def _require_supported_symbol(self, symbol: str | None) -> str:
        """Reject anything other than the one instrument this platform trades."""
        if symbol is None:
            return self.symbol
        if symbol.strip().upper() != self.symbol.upper():
            raise UnsupportedSymbolError(
                f"This platform trades {self.exchange}:{self.symbol} only. "
                f"Received '{symbol}'."
            )
        return self.symbol

    def _require_supported_interval(self, interval: Interval) -> Interval:
        supported = self._provider.capabilities.supported_intervals
        if interval not in supported:
            raise UnsupportedIntervalError(
                f"Provider '{self._provider.capabilities.name}' does not serve "
                f"the '{interval.value}' interval. "
                f"Supported: {', '.join(i.value for i in supported)}."
            )
        return interval

    # -- reads -----------------------------------------------------------

    async def get_current_quote(self, symbol: str | None = None) -> Quote:
        """Latest quote for the configured instrument.

        ``bid`` and ``ask`` may be ``None``: not every feed carries order-book
        depth. Check ``capabilities.supports_bid_ask`` before relying on them.
        """
        resolved = self._require_supported_symbol(symbol)
        return await self._provider.get_current_quote(resolved, self.exchange)

    async def get_historical_candles(
        self,
        interval: Interval = Interval.ONE_DAY,
        start: datetime | None = None,
        end: datetime | None = None,
        limit: int | None = None,
        symbol: str | None = None,
    ) -> CandleSeries:
        """OHLCV history for the configured instrument, oldest candle first."""
        resolved = self._require_supported_symbol(symbol)
        self._require_supported_interval(interval)

        effective_limit = min(limit or MAX_CANDLES, MAX_CANDLES)

        candles = await self._provider.get_historical_candles(
            symbol=resolved,
            exchange=self.exchange,
            interval=interval,
            start=start,
            end=end,
            limit=effective_limit,
        )

        return CandleSeries(
            symbol=resolved,
            exchange=self.exchange,
            interval=interval,
            provider=self._provider.capabilities.name,
            count=len(candles),
            candles=candles,
        )

    def subscribe_live_data(self, symbol: str | None = None):
        """Open a push subscription.

        Raises ``LiveDataNotSupportedError`` when the configured provider has
        no streaming feed. The WebSocket layer that consumes this arrives in a
        later stage; the method exists now so the abstraction is complete.
        """
        resolved = self._require_supported_symbol(symbol)
        return self._provider.subscribe_live_data(resolved, self.exchange)
