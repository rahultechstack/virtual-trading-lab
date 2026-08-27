"""Crypto market-data provider and routing tests.

Two separable concerns:

* **Routing** -- an instrument reaches the feed configured for its asset class,
  and never the other one. Tested offline with stubs.
* **The feed itself** -- the crypto provider spells pair symbols correctly and
  declares honest capabilities. The one test that actually calls upstream is
  marked ``network`` and skipped by default, so the suite stays hermetic.
"""

from decimal import Decimal

import pytest

from app.market_data.crypto import YahooCryptoProvider
from app.market_data.instruments import (
    AssetClass,
    instrument_registry,
    resolve_instrument,
)
from app.market_data.registry import available_providers, create_provider
from app.market_data.router import (
    provider_for,
    provider_for_symbol,
    reset_providers,
)
from app.market_data.yahoo import YahooFinanceProvider
from app.schemas.market_data import Interval

D = Decimal


@pytest.fixture(autouse=True)
def _fresh_router():
    reset_providers()
    yield
    reset_providers()


# ==========================================================================
# Vendor symbol mapping
# ==========================================================================


def test_a_coin_is_asked_for_as_an_inr_pair():
    provider = YahooCryptoProvider(quote_currency="INR")
    assert provider._vendor_symbol("BTC", "CRYPTO") == "BTC-INR"
    assert provider._vendor_symbol("ETH", "CRYPTO") == "ETH-INR"


def test_the_quote_currency_is_configurable():
    provider = YahooCryptoProvider(quote_currency="USD")
    assert provider._vendor_symbol("BTC", "CRYPTO") == "BTC-USD"


def test_the_exchange_code_plays_no_part_in_a_crypto_pair():
    """Crypto has no listing venue, so the code must not leak into the symbol."""
    provider = YahooCryptoProvider(quote_currency="INR")
    assert provider._vendor_symbol("BTC", "CRYPTO") == "BTC-INR"
    assert provider._vendor_symbol("BTC", "NSE") == "BTC-INR"


def test_an_equity_still_gets_its_exchange_suffix():
    provider = YahooFinanceProvider()
    assert provider._vendor_symbol("RELIANCE", "NSE") == "RELIANCE.NS"
    assert provider._vendor_symbol("RELIANCE", "BSE") == "RELIANCE.BO"


def test_the_equity_provider_would_mangle_a_coin():
    """Why routing exists, stated as a test.

    Asked for BTC the equity provider produces "BTC" with no pair suffix,
    which is not the instrument anyone means. Routing is what prevents this.
    """
    assert YahooFinanceProvider()._vendor_symbol("BTC", "CRYPTO") == "BTC"


# ==========================================================================
# Capabilities are declared honestly
# ==========================================================================


def test_the_crypto_provider_admits_it_has_no_push_feed():
    capabilities = YahooCryptoProvider().capabilities
    assert capabilities.supports_live_stream is False
    assert any("poll" in limit.lower() for limit in capabilities.limitations)


def test_the_crypto_provider_admits_it_has_no_order_book():
    assert YahooCryptoProvider().capabilities.supports_bid_ask is False


def test_the_crypto_provider_documents_the_sub_paisa_exclusion():
    limitations = " ".join(YahooCryptoProvider().capabilities.limitations).lower()
    assert "0.01" in limitations


def test_the_crypto_provider_serves_the_intraday_intervals_a_chart_needs():
    supported = YahooCryptoProvider().capabilities.supported_intervals
    for interval in (Interval.ONE_MINUTE, Interval.FIVE_MINUTES, Interval.ONE_DAY):
        assert interval in supported


def test_subscribing_to_a_live_crypto_feed_refuses_rather_than_faking_it():
    from app.core.exceptions import LiveDataNotSupportedError

    with pytest.raises(LiveDataNotSupportedError):
        YahooCryptoProvider().subscribe_live_data("BTC", "CRYPTO")


# ==========================================================================
# Provider registration and routing
# ==========================================================================


def test_the_crypto_provider_is_registered_by_name():
    assert "yahoo_crypto" in available_providers()
    assert isinstance(create_provider("yahoo_crypto"), YahooCryptoProvider)


def test_a_coin_is_routed_to_the_crypto_feed():
    provider = provider_for_symbol("BTC")
    assert provider.capabilities.name == "yahoo_crypto"


def test_a_stock_is_routed_to_the_equity_feed():
    provider = provider_for_symbol("RELIANCE")
    assert provider.capabilities.name == "yahoo"


def test_the_two_asset_classes_get_different_provider_instances():
    assert provider_for_symbol("BTC") is not provider_for_symbol("RELIANCE")


def test_the_same_asset_class_reuses_one_instance():
    """One pooled HTTP client per class, not one per request."""
    assert provider_for_symbol("BTC") is provider_for_symbol("ETH")


def test_every_catalogued_instrument_routes_to_a_provider():
    for instrument in instrument_registry.all():
        assert provider_for(instrument) is not None


async def test_closing_providers_survives_a_client_that_cannot_be_closed():
    """Shutdown is best-effort: one bad client must not strand the rest."""
    from app.market_data import router as router_module

    class _Stubborn:
        capabilities = YahooCryptoProvider().capabilities

        async def aclose(self):
            raise RuntimeError("Event loop is closed")

    router_module._instances[AssetClass.CRYPTO] = _Stubborn()
    await router_module.close_providers()
    assert router_module._instances == {}


# ==========================================================================
# Availability verification
# ==========================================================================


async def test_availability_is_probed_against_the_routed_provider():
    """A coin must never be verified against the equity feed."""
    asked: list[tuple[str, str]] = []

    class _Recording:
        async def get_current_quote(self, symbol, exchange):
            asked.append((symbol, exchange))
            return object()

    instrument_registry.reset_availability()
    assert await instrument_registry.verify("BTC", _Recording()) is True
    assert asked == [("BTC", "CRYPTO")]
    instrument_registry.reset_availability()


async def test_a_symbol_the_provider_cannot_serve_is_reported_unavailable():
    class _Broken:
        async def get_current_quote(self, symbol, exchange):
            raise RuntimeError("no such pair")

    instrument_registry.reset_availability()
    assert await instrument_registry.verify("BTC", _Broken()) is False
    instrument_registry.reset_availability()


async def test_availability_is_probed_at_most_once_per_symbol():
    calls = 0

    class _Counting:
        async def get_current_quote(self, symbol, exchange):
            nonlocal calls
            calls += 1
            return object()

    instrument_registry.reset_availability()
    provider = _Counting()
    await instrument_registry.verify("ETH", provider)
    await instrument_registry.verify("ETH", provider)
    assert calls == 1
    instrument_registry.reset_availability()


# ==========================================================================
# Sub-paisa exclusion
# ==========================================================================


def test_no_catalogued_coin_is_a_sub_paisa_asset():
    """SHIB and its kind are excluded; the catalogue must stay that way.

    This is a documentation test: it fails loudly if someone adds an asset the
    paise-denominated ledger cannot price, rather than letting it round to
    zero at runtime.
    """
    excluded = {"SHIB", "PEPE", "BONK", "FLOKI"}
    catalogued = {i.symbol for i in instrument_registry.all(AssetClass.CRYPTO)}
    assert not (catalogued & excluded)


async def test_a_price_below_one_paisa_is_refused_rather_than_rounded_to_zero():
    """The provider must say it cannot price the asset, not return 0.00."""
    from app.core.exceptions import MarketDataUnavailableError

    provider = YahooCryptoProvider()

    async def _fake_fetch(vendor_symbol, params):
        return {"meta": {"regularMarketPrice": 0.0005, "currency": "INR"}}

    provider._fetch_chart = _fake_fetch

    with pytest.raises(MarketDataUnavailableError, match="below the smallest"):
        await provider.get_current_quote("SHIB", "CRYPTO")


# ==========================================================================
# Live feed -- opt in with `-m network`
# ==========================================================================


@pytest.mark.network
async def test_the_live_feed_serves_bitcoin_in_rupees():
    provider = YahooCryptoProvider()
    try:
        quote = await provider.get_current_quote("BTC", "CRYPTO")
    finally:
        await provider.aclose()

    assert quote.symbol == "BTC"
    assert quote.currency == "INR"
    assert quote.last_price > 0


@pytest.mark.network
async def test_the_live_crypto_feed_returns_weekend_bars():
    """The property that distinguishes a 24/7 series from an NSE one."""
    provider = YahooCryptoProvider()
    try:
        candles = await provider.get_historical_candles(
            "BTC", "CRYPTO", Interval.ONE_HOUR, limit=200
        )
    finally:
        await provider.aclose()

    weekdays = {candle.timestamp.weekday() for candle in candles}
    # 5 = Saturday, 6 = Sunday. An NSE series would contain neither.
    assert {5, 6} <= weekdays


@pytest.mark.network
async def test_every_catalogued_coin_is_actually_served():
    """Guards the promise that nothing is listed the feed cannot serve."""
    provider = YahooCryptoProvider()
    unavailable = []
    try:
        for instrument in instrument_registry.all(AssetClass.CRYPTO):
            try:
                await provider.get_current_quote(instrument.symbol, instrument.exchange)
            except Exception as exc:  # noqa: BLE001 - collect, do not abort
                unavailable.append((instrument.symbol, str(exc)))
    finally:
        await provider.aclose()

    assert not unavailable, f"catalogued but unavailable: {unavailable}"
