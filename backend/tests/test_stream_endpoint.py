"""WebSocket endpoint tests.

Uses Starlette's TestClient, which drives the ASGI app directly -- no server,
no network. The provider is replaced with a fast, seeded mock so ticks arrive
promptly and deterministically.
"""

from decimal import Decimal

import pytest
from fastapi.testclient import TestClient

from app.main import app
from app.market_data.mock import MockMarketDataProvider
from app.realtime import price_stream as stream_module
from app.realtime.connection_manager import ConnectionManager
from app.realtime.price_stream import PriceStreamService

WS_URL = "/api/v1/stream/prices"
STATUS_URL = "/api/v1/stream/status"

D = Decimal


@pytest.fixture
def fast_stream():
    """Point the endpoint's module-level singletons at a fast mock stream."""
    manager = ConnectionManager(max_connections=3)
    service = PriceStreamService(
        provider=MockMarketDataProvider(seed=11, tick_interval_seconds=0.01),
        manager=manager,
        symbol="RELIANCE",
        exchange="NSE",
        poll_interval_seconds=0.05,
    )
    stream_module._manager = manager
    stream_module._service = service

    yield service

    stream_module._manager = None
    stream_module._service = None


@pytest.fixture
def client(fast_stream) -> TestClient:
    with TestClient(app) as test_client:
        yield test_client


def _read_until(socket, wanted: str, limit: int = 25) -> dict:
    """Pull frames until one of ``wanted`` type arrives."""
    for _ in range(limit):
        message = socket.receive_json()
        if message.get("type") == wanted:
            return message
    raise AssertionError(f"no {wanted!r} frame within {limit} messages")


# ==========================================================================
# Handshake
# ==========================================================================


def test_a_client_receives_a_status_frame_on_connect(client):
    with client.websocket_connect(WS_URL) as socket:
        message = socket.receive_json()

        assert message["type"] == "status"
        assert message["data"]["symbol"] == "RELIANCE"
        assert message["data"]["provider"] == "mock"
        assert message["data"]["is_mock"] is True


def test_the_stream_starts_on_the_first_client(client, fast_stream):
    assert fast_stream.is_running is False

    with client.websocket_connect(WS_URL) as socket:
        socket.receive_json()
        assert fast_stream.is_running is True


def test_ticks_arrive_without_the_client_asking(client):
    with client.websocket_connect(WS_URL) as socket:
        tick = _read_until(socket, "tick")

        data = tick["data"]
        assert data["symbol"] == "RELIANCE"
        assert data["exchange"] == "NSE"
        for field in ("last_price", "bid", "ask", "volume", "timestamp"):
            assert data[field] is not None, f"missing {field}"


def test_prices_update_over_successive_ticks(client):
    """The point of the whole stage: the price changes without a refresh."""
    with client.websocket_connect(WS_URL) as socket:
        prices = []
        for _ in range(30):
            message = socket.receive_json()
            if message["type"] == "tick":
                prices.append(message["data"]["last_price"])
            if len(prices) >= 6:
                break

    assert len(prices) >= 2
    assert len(set(prices)) > 1, "the price never moved"


def test_a_late_joiner_gets_the_last_known_price_immediately(client):
    with client.websocket_connect(WS_URL) as first:
        _read_until(first, "tick")

        with client.websocket_connect(WS_URL) as second:
            assert second.receive_json()["type"] == "status"
            # Then the subscription confirmation for the default instrument,
            # and the cached tick -- no waiting for the next interval.
            assert second.receive_json()["type"] == "subscription"
            assert second.receive_json()["type"] == "tick"


# ==========================================================================
# Heartbeat
# ==========================================================================


def test_ping_is_answered_with_pong(client):
    with client.websocket_connect(WS_URL) as socket:
        socket.receive_json()
        socket.send_json({"type": "ping"})

        assert _read_until(socket, "pong")["type"] == "pong"


def test_an_unknown_message_is_ignored_not_fatal(client):
    with client.websocket_connect(WS_URL) as socket:
        socket.receive_json()
        socket.send_json({"type": "please-buy-me-a-pony"})

        # The socket stays usable.
        socket.send_json({"type": "ping"})
        assert _read_until(socket, "pong")


# ==========================================================================
# Disconnection and limits
# ==========================================================================


def test_disconnecting_frees_the_slot(client, fast_stream):
    manager = stream_module._manager

    with client.websocket_connect(WS_URL) as socket:
        socket.receive_json()
        assert manager.connection_count == 1

    assert manager.connection_count == 0


def test_several_clients_all_receive_the_broadcast(client):
    with client.websocket_connect(WS_URL) as one, client.websocket_connect(
        WS_URL
    ) as two:
        assert _read_until(one, "tick")["data"]["symbol"] == "RELIANCE"
        assert _read_until(two, "tick")["data"]["symbol"] == "RELIANCE"


def test_the_connection_limit_is_refused_with_a_reason(client):
    """The third client is rejected; the limit in the fixture is three."""
    with client.websocket_connect(WS_URL) as a, client.websocket_connect(
        WS_URL
    ) as b, client.websocket_connect(WS_URL) as c:
        for socket in (a, b, c):
            socket.receive_json()

        with client.websocket_connect(WS_URL) as overflow:
            message = overflow.receive_json()

    assert message["type"] == "error"
    assert message["data"]["fatal"] is True
    assert "already connected" in message["data"]["message"]


# ==========================================================================
# Status endpoint
# ==========================================================================


def test_status_endpoint_reports_the_provider_and_mode(client):
    body = client.get(STATUS_URL).json()

    assert body["provider"] == "mock"
    assert body["is_mock"] is True
    assert body["mode"] == "push"
    assert body["symbol"] == "RELIANCE"


def test_status_endpoint_counts_live_connections(client):
    with client.websocket_connect(WS_URL) as socket:
        socket.receive_json()
        assert client.get(STATUS_URL).json()["connections"] == 1

    assert client.get(STATUS_URL).json()["connections"] == 0
