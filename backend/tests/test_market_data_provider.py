"""Provider-level tests.

Every request is served by an httpx MockTransport, so these run offline and
deterministically. They verify that the Yahoo payload shape is mapped onto the
platform's models correctly -- and that the provider is honest about what it
cannot do.
"""

from datetime import UTC, datetime
from decimal import Decimal

import httpx
import pytest

from app.core.exceptions import (
    LiveDataNotSupportedError,
    MarketDataUnavailableError,
    UnsupportedIntervalError,
)
from app.market_data.yahoo import YahooFinanceProvider
from app.schemas.market_data import Interval
from tests.fixtures.yahoo_payloads import (
    CANDLES_PAYLOAD,
    EMPTY_META_PAYLOAD,
    QUOTE_PAYLOAD,
    UNKNOWN_SYMBOL_PAYLOAD,
)


def _provider_returning(payload: dict, status_code: int = 200):
    """A YahooFinanceProvider whose HTTP client is stubbed out."""
    captured: dict[str, httpx.Request] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        captured["request"] = request
        return httpx.Response(status_code, json=payload)

    provider = YahooFinanceProvider()
    provider._client = httpx.AsyncClient(
        transport=httpx.MockTransport(handler),
        base_url="https://query1.finance.yahoo.com/v8/finance/chart",
    )
    return provider, captured


# --------------------------------------------------------------------------
# Quotes
# --------------------------------------------------------------------------


async def test_quote_maps_every_required_field():
    provider, _ = _provider_returning(QUOTE_PAYLOAD)

    quote = await provider.get_current_quote("RELIANCE", "NSE")

    assert quote.symbol == "RELIANCE"
    assert quote.exchange == "NSE"
    assert quote.last_price == Decimal("1314.30")
    assert quote.volume == 6346700
    assert quote.timestamp == datetime.fromtimestamp(1787650652, tz=UTC)
    await provider.aclose()


async def test_quote_bid_and_ask_are_none_because_the_feed_has_no_depth():
    """Documented limitation, asserted so it cannot regress into a fake value."""
    provider, _ = _provider_returning(QUOTE_PAYLOAD)

    quote = await provider.get_current_quote("RELIANCE", "NSE")

    assert quote.bid is None
    assert quote.ask is None
    assert provider.capabilities.supports_bid_ask is False
    await provider.aclose()


async def test_quote_carries_provenance():
    provider, _ = _provider_returning(QUOTE_PAYLOAD)

    quote = await provider.get_current_quote("RELIANCE", "NSE")

    assert quote.provider == "yahoo"
    assert quote.is_delayed is False
    assert quote.currency == "INR"
    assert quote.previous_close == Decimal("1309.80")
    await provider.aclose()


async def test_previous_close_falls_back_to_the_daily_key():
    """interval=1d payloads carry chartPreviousClose, not previousClose."""
    provider, _ = _provider_returning(QUOTE_PAYLOAD)

    quote = await provider.get_current_quote("RELIANCE", "NSE")

    assert quote.previous_close == Decimal("1309.80")
    await provider.aclose()


async def test_day_open_comes_from_the_session_bar():
    """meta has no day-open field; it must be read from the bar series."""
    provider, _ = _provider_returning(QUOTE_PAYLOAD)

    quote = await provider.get_current_quote("RELIANCE", "NSE")

    assert quote.day_open == Decimal("1304.30")
    assert quote.day_high == Decimal("1319.90")
    assert quote.day_low == Decimal("1301.05")
    await provider.aclose()


async def test_prices_are_exact_decimals_not_floats():
    provider, _ = _provider_returning(QUOTE_PAYLOAD)

    quote = await provider.get_current_quote("RELIANCE", "NSE")

    assert isinstance(quote.last_price, Decimal)
    assert quote.last_price == Decimal("1314.30")
    assert str(quote.last_price) == "1314.30"
    await provider.aclose()


async def test_nse_symbol_gets_the_yahoo_suffix():
    provider, captured = _provider_returning(QUOTE_PAYLOAD)

    await provider.get_current_quote("RELIANCE", "NSE")

    assert "RELIANCE.NS" in str(captured["request"].url)
    await provider.aclose()


# --------------------------------------------------------------------------
# Candles
# --------------------------------------------------------------------------


async def test_candles_are_parsed_oldest_first():
    provider, _ = _provider_returning(CANDLES_PAYLOAD)

    candles = await provider.get_historical_candles(
        "RELIANCE", "NSE", Interval.ONE_DAY
    )

    assert len(candles) == 3  # the null row is dropped
    assert [c.timestamp for c in candles] == sorted(c.timestamp for c in candles)
    first = candles[0]
    assert first.open == Decimal("1290.50")
    assert first.high == Decimal("1304.60")  # rounded from 1304.5999755859375
    assert first.low == Decimal("1288.00")
    assert first.close == Decimal("1301.00")
    assert first.volume == 4210000
    await provider.aclose()


async def test_candles_with_null_ohlc_are_dropped_not_filled():
    """A holiday must not appear as a fabricated flat bar."""
    provider, _ = _provider_returning(CANDLES_PAYLOAD)

    candles = await provider.get_historical_candles(
        "RELIANCE", "NSE", Interval.ONE_DAY
    )

    assert len(candles) == 3
    assert datetime.fromtimestamp(1787270400, tz=UTC) not in [
        c.timestamp for c in candles
    ]
    await provider.aclose()


async def test_candle_limit_keeps_the_most_recent_bars():
    provider, _ = _provider_returning(CANDLES_PAYLOAD)

    candles = await provider.get_historical_candles(
        "RELIANCE", "NSE", Interval.ONE_DAY, limit=2
    )

    assert len(candles) == 2
    assert candles[-1].close == Decimal("1319.40")
    await provider.aclose()


async def test_explicit_window_is_sent_as_period_params():
    provider, captured = _provider_returning(CANDLES_PAYLOAD)

    await provider.get_historical_candles(
        "RELIANCE",
        "NSE",
        Interval.ONE_DAY,
        start=datetime(2026, 8, 1, tzinfo=UTC),
        end=datetime(2026, 8, 20, tzinfo=UTC),
    )

    url = str(captured["request"].url)
    assert "period1=" in url and "period2=" in url
    assert "range=" not in url
    await provider.aclose()


async def test_omitted_window_falls_back_to_a_default_range():
    provider, captured = _provider_returning(CANDLES_PAYLOAD)

    await provider.get_historical_candles("RELIANCE", "NSE", Interval.ONE_DAY)

    assert "range=1y" in str(captured["request"].url)
    await provider.aclose()


# --------------------------------------------------------------------------
# Failure handling
# --------------------------------------------------------------------------


async def test_upstream_http_error_becomes_market_data_unavailable():
    provider, _ = _provider_returning({}, status_code=500)

    with pytest.raises(MarketDataUnavailableError):
        await provider.get_current_quote("RELIANCE", "NSE")
    await provider.aclose()


async def test_rate_limit_becomes_market_data_unavailable():
    provider, _ = _provider_returning({}, status_code=429)

    with pytest.raises(MarketDataUnavailableError) as exc:
        await provider.get_current_quote("RELIANCE", "NSE")
    assert "429" in str(exc.value)
    await provider.aclose()


async def test_unknown_symbol_payload_is_reported_not_swallowed():
    provider, _ = _provider_returning(UNKNOWN_SYMBOL_PAYLOAD)

    with pytest.raises(MarketDataUnavailableError):
        await provider.get_current_quote("NOSUCH", "NSE")
    await provider.aclose()


async def test_missing_price_is_an_error_rather_than_a_zero_quote():
    provider, _ = _provider_returning(EMPTY_META_PAYLOAD)

    with pytest.raises(MarketDataUnavailableError):
        await provider.get_current_quote("RELIANCE", "NSE")
    await provider.aclose()


async def test_network_failure_becomes_market_data_unavailable():
    def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("connection refused")

    provider = YahooFinanceProvider()
    provider._client = httpx.AsyncClient(
        transport=httpx.MockTransport(handler),
        base_url="https://query1.finance.yahoo.com/v8/finance/chart",
    )

    with pytest.raises(MarketDataUnavailableError):
        await provider.get_current_quote("RELIANCE", "NSE")
    await provider.aclose()


# --------------------------------------------------------------------------
# Honest capability reporting
# --------------------------------------------------------------------------


async def test_live_streaming_raises_instead_of_polling_behind_the_scenes():
    provider, _ = _provider_returning(QUOTE_PAYLOAD)

    with pytest.raises(LiveDataNotSupportedError):
        provider.subscribe_live_data("RELIANCE", "NSE")

    assert provider.capabilities.supports_live_stream is False
    await provider.aclose()


async def test_capabilities_spell_out_the_limitations():
    provider, _ = _provider_returning(QUOTE_PAYLOAD)

    caps = provider.capabilities

    assert caps.supports_quotes is True
    assert caps.supports_historical is True
    assert caps.requires_credentials is False
    assert any("bid/ask" in item for item in caps.limitations)
    assert any("streaming" in item.lower() for item in caps.limitations)
    await provider.aclose()


async def test_unsupported_interval_is_rejected():
    provider, _ = _provider_returning(CANDLES_PAYLOAD)
    # Simulate a provider build that does not serve minute bars.
    from app.market_data import yahoo

    original = yahoo._INTERVAL.pop(Interval.ONE_MINUTE)
    try:
        with pytest.raises(UnsupportedIntervalError):
            await provider.get_historical_candles(
                "RELIANCE", "NSE", Interval.ONE_MINUTE
            )
    finally:
        yahoo._INTERVAL[Interval.ONE_MINUTE] = original
    await provider.aclose()
