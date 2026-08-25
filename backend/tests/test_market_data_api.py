"""Service and endpoint tests.

The provider is replaced with an in-memory fake via FastAPI's dependency
override, so these assert the platform's own rules -- single instrument,
interval validation, error mapping -- with no network and no real vendor.
"""

from datetime import UTC, datetime
from decimal import Decimal

import pytest
from httpx import ASGITransport, AsyncClient

from app.core.exceptions import (
    LiveDataNotSupportedError,
    MarketDataUnavailableError,
    UnsupportedIntervalError,
    UnsupportedSymbolError,
)
from app.main import app
from app.market_data.base import MarketDataProvider
from app.market_data.registry import get_provider
from app.schemas.market_data import Candle, Interval, ProviderCapabilities, Quote
from app.services.market_data_service import RelianceMarketDataService

BASE = "/api/v1/market-data"


class FakeProvider(MarketDataProvider):
    """A provider with no I/O, used to prove the abstraction holds."""

    def __init__(
        self,
        *,
        supports_bid_ask: bool = True,
        supports_live_stream: bool = False,
        intervals: list[Interval] | None = None,
        fail_with: Exception | None = None,
    ) -> None:
        self._supports_bid_ask = supports_bid_ask
        self._supports_live_stream = supports_live_stream
        self._intervals = intervals or [Interval.ONE_DAY, Interval.ONE_MINUTE]
        self._fail_with = fail_with
        self.calls: list[tuple] = []

    @property
    def capabilities(self) -> ProviderCapabilities:
        return ProviderCapabilities(
            name="fake",
            supports_quotes=True,
            supports_historical=True,
            supports_bid_ask=self._supports_bid_ask,
            supports_live_stream=self._supports_live_stream,
            is_delayed=True,
            quote_delay_minutes=15,
            requires_credentials=True,
            supported_intervals=self._intervals,
            limitations=["fake provider for tests"],
        )

    async def get_current_quote(self, symbol: str, exchange: str) -> Quote:
        if self._fail_with:
            raise self._fail_with
        self.calls.append(("quote", symbol, exchange))
        return Quote(
            symbol=symbol,
            exchange=exchange,
            last_price=Decimal("1314.30"),
            bid=Decimal("1314.25") if self._supports_bid_ask else None,
            ask=Decimal("1314.35") if self._supports_bid_ask else None,
            volume=6346700,
            timestamp=datetime(2026, 8, 25, 9, 37, tzinfo=UTC),
            previous_close=Decimal("1309.80"),
            currency="INR",
            provider="fake",
            is_delayed=True,
        )

    async def get_historical_candles(
        self, symbol, exchange, interval, start=None, end=None, limit=None
    ) -> list[Candle]:
        if self._fail_with:
            raise self._fail_with
        self.calls.append(("candles", symbol, exchange, interval, start, end, limit))
        return [
            Candle(
                timestamp=datetime(2026, 8, 24, tzinfo=UTC),
                open=Decimal("1290.50"),
                high=Decimal("1304.60"),
                low=Decimal("1288.00"),
                close=Decimal("1301.00"),
                volume=4210000,
            ),
            Candle(
                timestamp=datetime(2026, 8, 25, tzinfo=UTC),
                open=Decimal("1301.00"),
                high=Decimal("1322.00"),
                low=Decimal("1298.60"),
                close=Decimal("1319.40"),
                volume=5120300,
            ),
        ]


@pytest.fixture
def fake_provider() -> FakeProvider:
    provider = FakeProvider()
    app.dependency_overrides[get_provider] = lambda: provider
    yield provider
    app.dependency_overrides.pop(get_provider, None)


@pytest.fixture
async def market_client(fake_provider) -> AsyncClient:
    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test"
    ) as client:
        yield client


# --------------------------------------------------------------------------
# Quote endpoint
# --------------------------------------------------------------------------


async def test_quote_endpoint_returns_every_required_field(market_client):
    response = await market_client.get(f"{BASE}/quote")

    assert response.status_code == 200
    body = response.json()
    for field in ("symbol", "exchange", "last_price", "bid", "ask", "volume", "timestamp"):
        assert field in body, f"missing required field: {field}"
    assert body["symbol"] == "RELIANCE"
    assert body["exchange"] == "NSE"
    assert Decimal(body["last_price"]) == Decimal("1314.30")
    assert body["volume"] == 6346700


async def test_quote_endpoint_reports_delay_status(market_client):
    body = (await market_client.get(f"{BASE}/quote")).json()

    assert body["is_delayed"] is True
    assert body["provider"] == "fake"


async def test_quote_rejects_any_symbol_other_than_reliance(market_client):
    response = await market_client.get(f"{BASE}/quote", params={"symbol": "TCS"})

    assert response.status_code == 400
    assert response.json()["error"]["code"] == "unsupported_symbol"


async def test_quote_accepts_reliance_explicitly(market_client):
    response = await market_client.get(f"{BASE}/quote", params={"symbol": "reliance"})

    assert response.status_code == 200
    assert response.json()["symbol"] == "RELIANCE"


async def test_provider_outage_maps_to_503(fake_provider):
    app.dependency_overrides[get_provider] = lambda: FakeProvider(
        fail_with=MarketDataUnavailableError("upstream down")
    )
    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test"
    ) as client:
        response = await client.get(f"{BASE}/quote")

    assert response.status_code == 503
    assert response.json()["error"]["code"] == "market_data_unavailable"


# --------------------------------------------------------------------------
# Candles endpoint
# --------------------------------------------------------------------------


async def test_candles_endpoint_returns_ohlcv_series(market_client):
    response = await market_client.get(f"{BASE}/candles", params={"interval": "1d"})

    assert response.status_code == 200
    body = response.json()
    assert body["symbol"] == "RELIANCE"
    assert body["interval"] == "1d"
    assert body["count"] == 2
    candle = body["candles"][0]
    for field in ("timestamp", "open", "high", "low", "close", "volume"):
        assert field in candle, f"missing required field: {field}"


async def test_candles_default_to_daily_interval(market_client, fake_provider):
    await market_client.get(f"{BASE}/candles")

    assert fake_provider.calls[0][3] == Interval.ONE_DAY


async def test_candles_forward_the_requested_window(market_client, fake_provider):
    await market_client.get(
        f"{BASE}/candles",
        params={
            "interval": "1d",
            "start": "2026-08-01T00:00:00Z",
            "end": "2026-08-20T00:00:00Z",
            "limit": 50,
        },
    )

    _, _, _, interval, start, end, limit = fake_provider.calls[0]
    assert interval == Interval.ONE_DAY
    assert start == datetime(2026, 8, 1, tzinfo=UTC)
    assert end == datetime(2026, 8, 20, tzinfo=UTC)
    assert limit == 50


async def test_candles_reject_an_interval_the_provider_cannot_serve():
    app.dependency_overrides[get_provider] = lambda: FakeProvider(
        intervals=[Interval.ONE_DAY]
    )
    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test"
    ) as client:
        response = await client.get(f"{BASE}/candles", params={"interval": "1m"})
    app.dependency_overrides.pop(get_provider, None)

    assert response.status_code == 400
    assert response.json()["error"]["code"] == "unsupported_interval"


async def test_candles_reject_an_unknown_interval_at_validation(market_client):
    response = await market_client.get(f"{BASE}/candles", params={"interval": "3s"})

    assert response.status_code == 422


async def test_candles_reject_a_foreign_symbol(market_client):
    response = await market_client.get(f"{BASE}/candles", params={"symbol": "INFY"})

    assert response.status_code == 400
    assert response.json()["error"]["code"] == "unsupported_symbol"


# --------------------------------------------------------------------------
# Capability disclosure
# --------------------------------------------------------------------------


async def test_provider_endpoint_discloses_capabilities(market_client):
    response = await market_client.get(f"{BASE}/provider")

    assert response.status_code == 200
    body = response.json()
    assert body["name"] == "fake"
    assert body["supports_bid_ask"] is True
    assert body["supports_live_stream"] is False
    assert body["quote_delay_minutes"] == 15
    assert body["limitations"]


# --------------------------------------------------------------------------
# Service layer directly
# --------------------------------------------------------------------------


async def test_service_returns_none_bid_ask_when_provider_lacks_depth():
    service = RelianceMarketDataService(FakeProvider(supports_bid_ask=False))

    quote = await service.get_current_quote()

    assert quote.bid is None
    assert quote.ask is None


async def test_service_rejects_other_symbols():
    service = RelianceMarketDataService(FakeProvider())

    with pytest.raises(UnsupportedSymbolError):
        await service.get_current_quote("HDFCBANK")


async def test_service_rejects_unsupported_interval():
    service = RelianceMarketDataService(FakeProvider(intervals=[Interval.ONE_DAY]))

    with pytest.raises(UnsupportedIntervalError):
        await service.get_historical_candles(interval=Interval.ONE_MINUTE)


async def test_service_caps_the_candle_limit():
    provider = FakeProvider()
    service = RelianceMarketDataService(provider)

    await service.get_historical_candles(interval=Interval.ONE_DAY, limit=999_999)

    assert provider.calls[0][6] == 5000


async def test_service_surfaces_live_stream_refusal():
    service = RelianceMarketDataService(FakeProvider(supports_live_stream=False))

    with pytest.raises(LiveDataNotSupportedError):
        service.subscribe_live_data()


async def test_service_is_provider_agnostic():
    """The same service works over any implementation of the contract."""
    for provider in (FakeProvider(supports_bid_ask=True), FakeProvider(supports_bid_ask=False)):
        service = RelianceMarketDataService(provider)
        quote = await service.get_current_quote()
        assert quote.symbol == "RELIANCE"
        assert quote.last_price == Decimal("1314.30")
