"""Market-data service for the supported instrument universe.

Sits between the API and whatever provider is configured. It owns the rules
that are true of *this platform* rather than of any feed:

* only instruments in the supported universe may be requested;
* the interval requested must be one the serving provider actually supports;
* results are wrapped in the platform's own response models.

**Providers are per asset class.** The service resolves the instrument, then
asks ``app.market_data.router`` which feed serves it -- so a crypto symbol is
never priced off the equity feed, and neither this class nor the API knows
which feed that is. A provider passed to the constructor overrides the routing
for every asset class, which is what tests do.

It depends only on ``MarketDataProvider``, never on a concrete vendor.
"""

from datetime import datetime

from app.core.config import settings
from app.core.exceptions import UnsupportedIntervalError
from app.market_data.instruments import resolve_instrument
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
#:
#: Reads through to settings so there is one place to change it. Kept as a
#: module attribute because callers and tests already import this name.
MAX_CANDLES = settings.MAX_CANDLES_PER_REQUEST


class MarketDataService:
    """Market data for any instrument in the supported universe."""

    def __init__(self, provider: MarketDataProvider | None = None) -> None:
        #: An explicitly injected provider serves EVERY asset class. Left None,
        #: each instrument is served by the feed routed for its class.
        self._provider = provider

    def provider_for(self, instrument) -> MarketDataProvider:
        """The feed serving one instrument."""
        if self._provider is not None:
            return self._provider

        from app.market_data.router import provider_for

        return provider_for(instrument)

    @property
    def symbol(self) -> str:
        """The default instrument, used when a request omits a symbol."""
        return settings.TRADING_SYMBOL

    @property
    def exchange(self) -> str:
        """Exchange of the default instrument."""
        return resolve_instrument(None).exchange

    @property
    def capabilities(self) -> ProviderCapabilities:
        """What the feed serving the DEFAULT instrument can do.

        Capabilities differ per asset class, so prefer
        ``capabilities_for(symbol)`` when the instrument is known.
        """
        return self.provider_for(resolve_instrument(None)).capabilities

    def capabilities_for(self, symbol: str | None = None) -> ProviderCapabilities:
        """What the feed serving ``symbol`` can actually do."""
        return self.provider_for(resolve_instrument(symbol)).capabilities

    # -- validation ------------------------------------------------------

    def _require_supported_symbol(self, symbol: str | None):
        """Resolve to a supported instrument, or reject.

        Delegates to the instrument registry, which is the single place the
        backend decides what may be traded -- so this service, the trading
        engine and the automation service can never disagree.
        """
        return resolve_instrument(symbol)

    def _require_supported_interval(
        self, interval: Interval, provider: MarketDataProvider
    ) -> Interval:
        """Check the interval against the feed that will actually serve it."""
        supported = provider.capabilities.supported_intervals
        if interval not in supported:
            raise UnsupportedIntervalError(
                f"Provider '{provider.capabilities.name}' does not serve "
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
        instrument = self._require_supported_symbol(symbol)
        return await self.provider_for(instrument).get_current_quote(
            instrument.symbol, instrument.exchange
        )

    async def get_historical_candles(
        self,
        interval: Interval = Interval.ONE_DAY,
        start: datetime | None = None,
        end: datetime | None = None,
        limit: int | None = None,
        symbol: str | None = None,
    ) -> CandleSeries:
        """OHLCV history for the configured instrument, oldest candle first."""
        instrument = self._require_supported_symbol(symbol)
        provider = self.provider_for(instrument)
        self._require_supported_interval(interval, provider)

        cap = settings.MAX_CANDLES_PER_REQUEST
        effective_limit = min(limit or cap, cap)

        candles = await provider.get_historical_candles(
            symbol=instrument.symbol,
            exchange=instrument.exchange,
            interval=interval,
            start=start,
            end=end,
            limit=effective_limit,
        )

        return CandleSeries(
            symbol=instrument.symbol,
            exchange=instrument.exchange,
            interval=interval,
            provider=provider.capabilities.name,
            count=len(candles),
            candles=candles,
        )

    def subscribe_live_data(self, symbol: str | None = None):
        """Open a push subscription.

        Raises ``LiveDataNotSupportedError`` when the configured provider has
        no streaming feed. The WebSocket layer that consumes this arrives in a
        later stage; the method exists now so the abstraction is complete.
        """
        instrument = self._require_supported_symbol(symbol)
        return self.provider_for(instrument).subscribe_live_data(
            instrument.symbol, instrument.exchange
        )


#: Back-compat alias. The service was single-instrument when it was named for
#: RELIANCE; it now serves the whole universe. Existing imports keep working.
RelianceMarketDataService = MarketDataService
