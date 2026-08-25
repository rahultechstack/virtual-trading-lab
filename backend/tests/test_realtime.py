"""Real-time streaming: connection manager, mock provider and price stream.

None of this touches the network or an external provider.
"""

import asyncio
from decimal import Decimal

import pytest

from app.core.exceptions import MarketDataUnavailableError
from app.market_data.mock import MockMarketDataProvider
from app.realtime.connection_manager import (
    ConnectionLimitReached,
    ConnectionManager,
)
from app.realtime.price_stream import BidAskSource, PriceStreamService, StreamMode
from app.schemas.market_data import Interval, Quote
from app.trading.spread import SpreadModel

D = Decimal


class FakeSocket:
    """Stands in for a WebSocket. Records what it was sent."""

    def __init__(self, *, fail_on_send: bool = False) -> None:
        self.sent: list[dict] = []
        self.accepted = False
        self.closed_with: int | None = None
        self.fail_on_send = fail_on_send
        self.client_state = None

    async def accept(self) -> None:
        self.accepted = True

    async def send_json(self, message: dict) -> None:
        if self.fail_on_send:
            raise ConnectionError("client is gone")
        self.sent.append(message)

    async def close(self, code: int = 1000) -> None:
        self.closed_with = code


# ==========================================================================
# ConnectionManager
# ==========================================================================


async def test_connect_accepts_and_registers():
    manager = ConnectionManager()
    socket = FakeSocket()

    await manager.connect(socket)

    assert socket.accepted
    assert manager.connection_count == 1
    assert manager.has_listeners
    assert manager.stats.total_accepted == 1


async def test_disconnect_removes_the_client():
    manager = ConnectionManager()
    socket = FakeSocket()
    await manager.connect(socket)

    await manager.disconnect(socket)

    assert manager.connection_count == 0
    assert manager.has_listeners is False
    assert manager.stats.total_disconnected == 1


async def test_disconnect_is_idempotent():
    manager = ConnectionManager()
    socket = FakeSocket()
    await manager.connect(socket)

    await manager.disconnect(socket)
    await manager.disconnect(socket)

    assert manager.stats.total_disconnected == 1, "the second call is a no-op"


async def test_broadcast_reaches_every_client():
    manager = ConnectionManager()
    sockets = [FakeSocket() for _ in range(3)]
    for socket in sockets:
        await manager.connect(socket)

    delivered = await manager.broadcast({"type": "tick", "data": {"x": 1}})

    assert delivered == 3
    for socket in sockets:
        assert socket.sent == [{"type": "tick", "data": {"x": 1}}]


async def test_broadcast_to_nobody_is_harmless():
    manager = ConnectionManager()

    assert await manager.broadcast({"type": "tick"}) == 0


async def test_a_dead_client_is_dropped_and_does_not_block_the_others():
    """One broken socket must not deny the broadcast to everyone else."""
    manager = ConnectionManager()
    healthy_one, dead, healthy_two = (
        FakeSocket(),
        FakeSocket(fail_on_send=True),
        FakeSocket(),
    )
    for socket in (healthy_one, dead, healthy_two):
        await manager.connect(socket)

    delivered = await manager.broadcast({"type": "tick"})

    assert delivered == 2
    assert manager.connection_count == 2, "the dead client was reaped"
    assert healthy_one.sent and healthy_two.sent
    assert manager.stats.send_failures == 1


async def test_the_connection_limit_is_enforced():
    manager = ConnectionManager(max_connections=2)
    for _ in range(2):
        await manager.connect(FakeSocket())

    with pytest.raises(ConnectionLimitReached):
        await manager.connect(FakeSocket())

    assert manager.connection_count == 2
    assert manager.stats.total_rejected == 1


async def test_a_rejected_client_is_never_accepted():
    manager = ConnectionManager(max_connections=1)
    await manager.connect(FakeSocket())
    rejected = FakeSocket()

    with pytest.raises(ConnectionLimitReached):
        await manager.connect(rejected)

    assert rejected.accepted is False


async def test_disconnect_all_clears_the_pool():
    manager = ConnectionManager()
    sockets = [FakeSocket() for _ in range(3)]
    for socket in sockets:
        await manager.connect(socket)

    await manager.disconnect_all()

    assert manager.connection_count == 0
    assert all(socket.closed_with == 1001 for socket in sockets)


async def test_concurrent_connects_and_broadcasts_do_not_race():
    """Membership changes and fan-out must not corrupt the pool."""
    manager = ConnectionManager(max_connections=100)
    sockets = [FakeSocket() for _ in range(20)]

    await asyncio.gather(*(manager.connect(socket) for socket in sockets))
    await asyncio.gather(*(manager.broadcast({"type": "tick"}) for _ in range(5)))

    assert manager.connection_count == 20
    assert all(len(socket.sent) == 5 for socket in sockets)


# ==========================================================================
# Mock provider
# ==========================================================================


async def test_mock_provider_declares_itself_as_mock():
    capabilities = MockMarketDataProvider().capabilities

    assert capabilities.is_mock is True
    assert capabilities.name == "mock"
    assert any("SIMULATED" in item for item in capabilities.limitations)


async def test_mock_quotes_are_flagged_as_mock():
    quote = await MockMarketDataProvider(seed=1).get_current_quote("RELIANCE", "NSE")

    assert quote.is_mock is True
    assert quote.provider == "mock"


async def test_mock_provider_supplies_bid_and_ask():
    """Unlike Yahoo, this one has depth -- synthesised, but present."""
    provider = MockMarketDataProvider(seed=1, spread_bps=D("4"))

    quote = await provider.get_current_quote("RELIANCE", "NSE")

    assert quote.bid is not None and quote.ask is not None
    assert quote.bid < quote.last_price < quote.ask
    assert provider.capabilities.supports_bid_ask is True


async def test_the_same_seed_gives_the_same_walk():
    a = MockMarketDataProvider(seed=42)
    b = MockMarketDataProvider(seed=42)

    first = await a.get_current_quote("RELIANCE", "NSE")
    second = await b.get_current_quote("RELIANCE", "NSE")

    assert first.last_price == second.last_price


async def test_the_price_actually_moves():
    provider = MockMarketDataProvider(seed=7, volatility_bps=D("50"))

    prices = [
        (await provider.get_current_quote("RELIANCE", "NSE")).last_price
        for _ in range(10)
    ]

    assert len(set(prices)) > 1, "a static price would not exercise the UI"


async def test_the_walk_stays_within_sane_bounds():
    provider = MockMarketDataProvider(seed=3, base_price=D("1000"), volatility_bps=D("500"))

    for _ in range(300):
        quote = await provider.get_current_quote("RELIANCE", "NSE")
        assert D("500") <= quote.last_price <= D("2000")


async def test_volume_only_ever_grows():
    provider = MockMarketDataProvider(seed=5)

    volumes = [
        (await provider.get_current_quote("RELIANCE", "NSE")).volume
        for _ in range(5)
    ]

    assert volumes == sorted(volumes)
    assert volumes[0] < volumes[-1]


async def test_mock_provider_generates_candles():
    provider = MockMarketDataProvider(seed=1)

    candles = await provider.get_historical_candles(
        "RELIANCE", "NSE", Interval.ONE_DAY, limit=10
    )

    assert len(candles) == 10
    assert [c.timestamp for c in candles] == sorted(c.timestamp for c in candles)
    for candle in candles:
        assert candle.low <= candle.open <= candle.high
        assert candle.low <= candle.close <= candle.high


async def test_mock_provider_streams():
    """It overrides subscribe_live_data rather than refusing."""
    provider = MockMarketDataProvider(seed=1, tick_interval_seconds=0.01)

    received: list[Quote] = []
    async for quote in provider.subscribe_live_data("RELIANCE", "NSE"):
        received.append(quote)
        if len(received) == 3:
            break

    assert len(received) == 3
    assert all(q.is_mock for q in received)


# ==========================================================================
# PriceStreamService
# ==========================================================================


class StubProvider(MockMarketDataProvider):
    """Mock provider with the streaming capability forced off."""

    name = "stub"

    @property
    def capabilities(self):
        base = super().capabilities
        return base.model_copy(update={"supports_live_stream": False, "name": "stub"})


def _service(provider, manager=None, **kwargs) -> PriceStreamService:
    return PriceStreamService(
        provider=provider,
        manager=manager or ConnectionManager(),
        symbol="RELIANCE",
        exchange="NSE",
        **kwargs,
    )


async def test_push_mode_is_chosen_when_the_provider_can_stream():
    service = _service(MockMarketDataProvider(seed=1))

    assert service.mode is StreamMode.PUSH


async def test_poll_mode_is_chosen_when_it_cannot():
    service = _service(StubProvider(seed=1))

    assert service.mode is StreamMode.POLL


async def test_a_tick_carries_every_field_the_ui_needs():
    service = _service(MockMarketDataProvider(seed=1))
    quote = await service._provider.get_current_quote("RELIANCE", "NSE")

    tick = service.build_tick(quote)

    assert tick["type"] == "tick"
    for field in ("symbol", "last_price", "bid", "ask", "volume", "timestamp"):
        assert field in tick["data"], f"missing required field: {field}"
    assert tick["data"]["symbol"] == "RELIANCE"


async def test_provider_supplied_depth_is_labelled_as_such():
    service = _service(MockMarketDataProvider(seed=1))
    quote = await service._provider.get_current_quote("RELIANCE", "NSE")

    tick = service.build_tick(quote)

    assert tick["data"]["bid_ask_source"] == BidAskSource.PROVIDER.value


async def test_missing_depth_is_modelled_and_labelled_modelled():
    """A derived spread must never be presented as a real order book."""
    service = _service(MockMarketDataProvider(seed=1))
    service._spread = SpreadModel(basis_points=D("20"))
    quote = (
        await service._provider.get_current_quote("RELIANCE", "NSE")
    ).model_copy(update={"bid": None, "ask": None})

    tick = service.build_tick(quote)

    assert tick["data"]["bid_ask_source"] == BidAskSource.MODELLED.value
    assert tick["data"]["bid"] is not None
    assert Decimal(tick["data"]["bid"]) < quote.last_price
    assert Decimal(tick["data"]["ask"]) > quote.last_price


async def test_depth_can_be_reported_unavailable_instead_of_modelled():
    service = _service(MockMarketDataProvider(seed=1), model_bid_ask=False)
    quote = (
        await service._provider.get_current_quote("RELIANCE", "NSE")
    ).model_copy(update={"bid": None, "ask": None})

    tick = service.build_tick(quote)

    assert tick["data"]["bid_ask_source"] == BidAskSource.UNAVAILABLE.value
    assert tick["data"]["bid"] is None


async def test_ticks_are_flagged_when_the_provider_is_mock():
    service = _service(MockMarketDataProvider(seed=1))
    quote = await service._provider.get_current_quote("RELIANCE", "NSE")

    assert service.build_tick(quote)["data"]["is_mock"] is True


async def test_a_tick_is_broadcast_to_connected_clients():
    manager = ConnectionManager()
    socket = FakeSocket()
    await manager.connect(socket)
    service = _service(MockMarketDataProvider(seed=1), manager)

    quote = await service._provider.get_current_quote("RELIANCE", "NSE")
    await service._broadcast_quote(quote)

    assert len(socket.sent) == 1
    assert socket.sent[0]["type"] == "tick"
    assert service.tick_count == 1
    assert service.last_tick is not None


async def test_polling_is_skipped_when_nobody_is_listening():
    """An idle browser must not burn upstream rate limit."""
    manager = ConnectionManager()
    service = _service(StubProvider(seed=1), manager)

    await service._poll_once()

    assert service.tick_count == 0


async def test_polling_runs_once_a_client_connects():
    manager = ConnectionManager()
    service = _service(StubProvider(seed=1), manager)
    await manager.connect(FakeSocket())

    await service._poll_once()

    assert service.tick_count == 1


async def test_an_upstream_failure_is_broadcast_not_raised():
    """The stream must survive a provider outage."""

    class BrokenProvider(StubProvider):
        async def get_current_quote(self, symbol: str, exchange: str):
            raise MarketDataUnavailableError("upstream is down")

    manager = ConnectionManager()
    socket = FakeSocket()
    await manager.connect(socket)
    service = _service(BrokenProvider(seed=1), manager)

    await service._poll_once()  # must not raise

    assert service.error_count == 1
    assert socket.sent[0]["type"] == "error"
    assert service.last_error is not None


async def test_the_stream_recovers_after_a_failure():
    manager = ConnectionManager()
    await manager.connect(FakeSocket())
    service = _service(StubProvider(seed=1), manager)

    await service._handle_failure(MarketDataUnavailableError("blip"))
    assert service.last_error is not None

    await service._poll_once()

    assert service.last_error is None, "a good tick clears the error"
    assert service.tick_count == 1


async def test_status_reports_the_mode_and_provider():
    service = _service(MockMarketDataProvider(seed=1))

    status = service.status()

    assert status["mode"] == "push"
    assert status["is_mock"] is True
    assert status["symbol"] == "RELIANCE"
    assert status["running"] is False


async def test_start_and_stop_are_clean():
    service = _service(StubProvider(seed=1), poll_interval_seconds=0.05)

    await service.start()
    assert service.is_running

    await service.stop()
    assert service.is_running is False


async def test_starting_twice_is_a_no_op():
    service = _service(StubProvider(seed=1), poll_interval_seconds=0.05)

    await service.start()
    await service.start()

    assert service.is_running
    await service.stop()


async def test_the_push_loop_broadcasts_until_stopped():
    manager = ConnectionManager()
    socket = FakeSocket()
    await manager.connect(socket)
    service = _service(
        MockMarketDataProvider(seed=1, tick_interval_seconds=0.01), manager
    )

    await service.start()
    await asyncio.sleep(0.12)
    await service.stop()

    assert service.tick_count >= 2
    assert all(message["type"] == "tick" for message in socket.sent)
