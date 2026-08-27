"""Cryptocurrency market data.

Kept in its own module because crypto is a different market, not a different
ticker: pairs are quoted against a currency, there is no exchange calendar, and
the limitations differ from an equity feed's. The rest of the application never
imports this -- it asks ``app.market_data.router.provider_for(instrument)`` and
receives whatever is configured.

**Which upstream.** The equity provider was not *assumed* to serve crypto; it
was probed. Yahoo's chart endpoint serves ``BTC-INR``, ``ETH-INR`` and the
other listed pairs with ``instrumentType: CRYPTOCURRENCY``, ``currency: INR``
and continuous 1m-1mo OHLCV -- including bars through weekends and overnight,
where an NSE symbol has none. Since it is the same transport, this provider
reuses ``YahooChartProvider`` for HTTP and parsing and overrides only what is
genuinely crypto-specific: the pair symbol, and the honest capability list.

**INR pairs, deliberately.** Asking for ``BTC-INR`` rather than ``BTC-USD``
keeps one currency across the whole portfolio. A USD pair would need an FX rate
on every valuation, and a wrong or stale rate would silently corrupt P&L for
the crypto half of the account.

**Swapping in a real exchange feed.** Write a class satisfying
``MarketDataProvider`` -- optionally overriding ``subscribe_live_data`` if it
has a push socket, which would let the stream run in PUSH mode for crypto while
equities stay on POLL -- and register it in ``app.market_data.registry``. Then
set ``CRYPTO_MARKET_DATA_PROVIDER``. Nothing else changes.
"""

from app.core.config import settings
from app.core.logging import get_logger
from app.market_data.yahoo import _INTERVAL, YahooChartProvider
from app.schemas.market_data import ProviderCapabilities

logger = get_logger(__name__)


class YahooCryptoProvider(YahooChartProvider):
    """Crypto spot prices, quoted in ``CRYPTO_QUOTE_CURRENCY``.

    The ``exchange`` argument is accepted for interface compatibility and
    ignored: crypto has no listing venue, and every catalogue entry carries the
    platform's own ``CRYPTO`` code rather than an exchange MIC.
    """

    name = "yahoo_crypto"

    def __init__(
        self,
        timeout_seconds: float | None = None,
        quote_currency: str | None = None,
    ) -> None:
        # The endpoint and user agent come from settings via the base class.
        super().__init__(timeout_seconds=timeout_seconds)
        self._quote_currency = (
            quote_currency or settings.CRYPTO_QUOTE_CURRENCY
        ).upper()

    @classmethod
    def from_settings(cls) -> "YahooCryptoProvider":
        return cls(
            timeout_seconds=settings.MARKET_DATA_TIMEOUT_SECONDS,
            quote_currency=settings.CRYPTO_QUOTE_CURRENCY,
        )

    @property
    def quote_currency(self) -> str:
        return self._quote_currency

    @property
    def default_currency(self) -> str:
        return self._quote_currency

    def _vendor_symbol(self, symbol: str, exchange: str) -> str:
        """``BTC`` -> ``BTC-INR``. The exchange code plays no part."""
        return f"{symbol.upper()}-{self._quote_currency}"

    @property
    def capabilities(self) -> ProviderCapabilities:
        return ProviderCapabilities(
            name=self.name,
            supports_quotes=True,
            supports_historical=True,
            supports_bid_ask=False,
            supports_live_stream=False,
            is_delayed=False,
            quote_delay_minutes=0,
            requires_credentials=False,
            supported_intervals=list(_INTERVAL.keys()),
            limitations=[
                "No bid/ask: this feed carries no order-book depth, so bid and "
                "ask are always null and the stream models them instead.",
                "No push feed: prices are POLLED on the stream interval, not "
                "streamed. They still update continuously, day and night, "
                "because the market never closes -- but the cadence is the "
                "poll interval, not the exchange's tick rate.",
                "Aggregated pricing: quotes are a cross-exchange composite, "
                "not one venue's book. No single exchange's fills would match "
                "them exactly.",
                "Unofficial API: undocumented and unsupported; it may "
                "rate-limit or change shape without notice.",
                "Assets priced below 0.01 in the quote currency cannot be "
                "represented by this platform's paise-denominated ledger and "
                "are excluded from the catalogue.",
            ],
        )
