"""Live price streaming.

Bridges a market-data provider to connected WebSocket clients:

    provider  ->  PriceStreamService  ->  ConnectionManager  ->  clients

It runs in whichever of two modes the configured provider can support, which
it decides from ``capabilities.supports_live_stream``:

* **Push** -- consume the provider's ``subscribe_live_data`` async iterator.
  Only the mock provider offers this today.
* **Poll** -- ask for a quote on a fixed interval via APScheduler. This is
  what Yahoo requires: it has no public push feed, so "real time" here means
  *polled frequently*, and the payload says so via ``is_delayed`` and
  ``mode``.

Polling pauses whenever no client is connected **and** nothing is armed, so an
idle server makes no upstream calls at all. An instrument with an ACTIVE
automatic order keeps being polled regardless of who is watching -- otherwise a
crypto stop-loss set on Friday would sit inert all weekend, which would make a
24/7 market pointless. See ``symbols_to_poll``.

Each symbol is fetched from the provider routed for **its own asset class**, so
an equity and a crypto subscription on the same socket are served by different
feeds without the stream knowing anything about either. Routing is opt-in
(``route_by_asset_class``): the process-wide stream turns it on, while a
caller that injects one provider -- a test, or a single-feed deployment --
keeps that provider for every symbol.

Failures are contained: an upstream error is broadcast as an error frame and
the loop keeps running with a backoff, rather than tearing the stream down.
"""

import asyncio
from datetime import UTC, datetime
from decimal import Decimal
from enum import StrEnum
from typing import Any

from apscheduler.schedulers.asyncio import AsyncIOScheduler

from app.core.config import settings
from app.core.exceptions import MarketDataError
from app.core.logging import get_logger
from app.market_data.base import MarketDataProvider
from app.realtime.connection_manager import ConnectionManager
from app.schemas.market_data import Quote
from app.trading.pnl import to_money
from app.trading.spread import SpreadModel

logger = get_logger(__name__)

_JOB_ID = "price-poll"


class StreamMode(StrEnum):
    PUSH = "push"
    POLL = "poll"


class BidAskSource(StrEnum):
    """Where the quoted depth came from.

    Surfaced on every tick so a modelled spread is never mistaken for a real
    order book.
    """

    PROVIDER = "provider"
    MODELLED = "modelled"
    UNAVAILABLE = "unavailable"


class PriceStreamService:
    """Obtains quotes and broadcasts them."""

    def __init__(
        self,
        *,
        provider: MarketDataProvider,
        manager: ConnectionManager,
        symbol: str,
        exchange: str,
        poll_interval_seconds: float = 5.0,
        model_bid_ask: bool = True,
        route_by_asset_class: bool = False,
    ) -> None:
        self._provider = provider
        self._manager = manager
        self._symbol = symbol
        self._exchange = exchange
        self._poll_interval = poll_interval_seconds
        self._model_bid_ask = model_bid_ask
        #: Off by default so an injected provider serves every symbol. The
        #: process-wide stream turns it on; see get_price_stream().
        self._route_by_asset_class = route_by_asset_class

        self._spread = SpreadModel.from_settings()
        self._scheduler: AsyncIOScheduler | None = None
        self._push_task: asyncio.Task | None = None
        self._running = False

        #: symbol -> most recent tick payload, so a client subscribing to an
        #: instrument can be shown a price immediately.
        self.last_ticks: dict[str, dict[str, Any]] = {}
        self.last_error: str | None = None
        self.tick_count = 0
        self.error_count = 0

    @property
    def last_tick(self) -> dict[str, Any] | None:
        """Most recent tick for the default instrument.

        Kept as a property so existing callers -- the snapshot scheduler and the
        stop-loss reference price among them -- keep working now that the
        stream carries several instruments at once.
        """
        return self.last_ticks.get(self._symbol.upper())

    def last_tick_for(self, symbol: str) -> dict[str, Any] | None:
        return self.last_ticks.get(symbol.upper())

    def symbols_to_poll(self) -> list[str]:
        """Which instruments to fetch this cycle.

        The union of two independent reasons to want a price:

        1. **Somebody is watching.** Exactly what clients subscribed to; the
           default instrument when a client has subscribed to nothing, which
           keeps a bare client working.
        2. **Something is armed.** Any instrument with an ACTIVE automatic
           order, so triggers keep being evaluated with every browser closed.

        Empty when neither applies -- an idle server makes no upstream calls.
        """
        wanted: set[str] = set()

        if self._manager.has_listeners:
            subscribed = self._manager.subscribed_symbols()
            wanted |= subscribed if subscribed else {self._symbol.upper()}

        wanted |= self.automation_symbols()
        return sorted(wanted)

    def provider_for_symbol(self, symbol: str) -> MarketDataProvider:
        """The feed that serves one symbol.

        With routing off, the provider this service was built with serves
        everything -- which is what a caller injecting a single feed means.
        With it on, each instrument is served by the feed configured for its
        asset class, so a crypto symbol is never priced off the equity feed.
        """
        if not self._route_by_asset_class:
            return self._provider

        from app.market_data.instruments import instrument_registry
        from app.market_data.router import provider_for

        instrument = instrument_registry.get(symbol)
        return provider_for(instrument) if instrument else self._provider

    @staticmethod
    def automation_symbols() -> set[str]:
        """Instruments that must be priced because a trigger is armed on them.

        Read from the monitor's cache rather than the database: this runs on
        every poll cycle, and the cache is refreshed by the evaluation path and
        invalidated whenever an order is created or cancelled.
        """
        if not settings.STREAM_POLL_FOR_AUTOMATION:
            return set()

        from app.automation.monitor import get_automatic_order_monitor

        return set(get_automatic_order_monitor().armed_symbols())

    # -- introspection ---------------------------------------------------

    @property
    def mode(self) -> StreamMode:
        return (
            StreamMode.PUSH
            if self._provider.capabilities.supports_live_stream
            else StreamMode.POLL
        )

    @property
    def is_running(self) -> bool:
        return self._running

    def status(self) -> dict[str, Any]:
        capabilities = self._provider.capabilities
        return {
            "running": self._running,
            "mode": self.mode.value,
            "provider": capabilities.name,
            "is_mock": capabilities.is_mock,
            "is_delayed": capabilities.is_delayed,
            "symbol": self._symbol,
            "subscribed_symbols": sorted(self._manager.subscribed_symbols()),
            "polled_symbols": self.symbols_to_poll(),
            "exchange": self._exchange,
            "poll_interval_seconds": self._poll_interval,
            "connections": self._manager.connection_count,
            "ticks_broadcast": self.tick_count,
            "errors": self.error_count,
            "last_error": self.last_error,
            "automation": self._automation_status(),
        }

    @staticmethod
    def _automation_status() -> dict[str, Any]:
        """Automatic-order counters, for the status endpoint."""
        from app.automation.monitor import get_automatic_order_monitor

        return get_automatic_order_monitor().status()

    # -- lifecycle -------------------------------------------------------

    async def start(self) -> None:
        """Begin streaming in whichever mode the provider supports."""
        if self._running:
            return
        self._running = True

        if self.mode is StreamMode.PUSH:
            self._push_task = asyncio.create_task(self._run_push_loop())
            logger.info(
                "Price stream started in PUSH mode via provider '%s'.",
                self._provider.capabilities.name,
            )
        else:
            self._scheduler = AsyncIOScheduler(timezone="UTC")
            self._scheduler.add_job(
                self._poll_once,
                trigger="interval",
                seconds=self._poll_interval,
                id=_JOB_ID,
                # A slow upstream must not pile up overlapping polls.
                max_instances=1,
                coalesce=True,
                misfire_grace_time=int(self._poll_interval) + 5,
            )
            self._scheduler.start()
            logger.info(
                "Price stream started in POLL mode via provider '%s' every %.1fs "
                "(no push feed available).",
                self._provider.capabilities.name,
                self._poll_interval,
            )

    async def stop(self) -> None:
        """Stop streaming and release the scheduler or task."""
        if not self._running:
            return
        self._running = False

        if self._push_task is not None:
            self._push_task.cancel()
            try:
                await self._push_task
            except (asyncio.CancelledError, Exception):  # noqa: BLE001
                pass
            self._push_task = None

        if self._scheduler is not None:
            self._scheduler.shutdown(wait=False)
            self._scheduler = None

        logger.info("Price stream stopped.")

    # -- modes -----------------------------------------------------------

    async def _run_push_loop(self) -> None:
        """Consume the provider's push feed until cancelled."""
        backoff = 1.0
        while self._running:
            try:
                async for quote in self._provider.subscribe_live_data(
                    self._symbol, self._exchange
                ):
                    if not self._running:
                        break
                    backoff = 1.0
                    await self._broadcast_quote(quote)
            except asyncio.CancelledError:
                raise
            except Exception as exc:  # noqa: BLE001 - the stream must survive
                await self._handle_failure(exc)
                # Back off before reattaching, so a persistently broken feed
                # does not spin.
                await asyncio.sleep(backoff)
                backoff = min(backoff * 2, 30.0)

    async def _poll_once(self) -> None:
        """One scheduled poll. Never raises -- the scheduler must keep going.

        Polls every subscribed instrument. One symbol failing does not stop the
        others: each is fetched and reported independently.
        """
        from app.market_data.instruments import instrument_registry

        for symbol in self.symbols_to_poll():
            instrument = instrument_registry.get(symbol)
            exchange = instrument.exchange if instrument else self._exchange
            # Each instrument is priced by the feed serving ITS asset class.
            # The stream itself knows nothing about stocks or crypto.
            provider = self.provider_for_symbol(symbol)
            try:
                quote = await provider.get_current_quote(symbol, exchange)
            except MarketDataError as exc:
                await self._handle_failure(exc, symbol=symbol)
                continue
            except Exception as exc:  # noqa: BLE001 - defensive
                await self._handle_failure(exc, symbol=symbol)
                continue

            await self._broadcast_quote(quote)

    # -- broadcasting ----------------------------------------------------

    async def _broadcast_quote(self, quote: Quote) -> None:
        payload = self.build_tick(quote)
        symbol = quote.symbol.upper()
        self.last_ticks[symbol] = payload
        self.tick_count += 1
        self.last_error = None
        # Routed by symbol, so a client watching TCS is not sent INFY ticks.
        await self._manager.broadcast(payload, symbol=symbol)
        await self._run_automation(quote.last_price, symbol=symbol)

    async def _run_automation(self, market_price: Decimal, *, symbol: str) -> None:
        """Let the automatic-order monitor act on this price.

        Runs after the tick is broadcast so the chart is never held up by
        order execution. Failures are contained inside the monitor; this
        wrapper is a second guard so the stream survives regardless.
        """
        # Imported here to keep the realtime package free of a hard
        # dependency on the trading stack at import time.
        from app.automation.monitor import get_automatic_order_monitor

        try:
            events = await get_automatic_order_monitor().on_price(
                market_price=market_price, symbol=symbol
            )
        except Exception as exc:  # noqa: BLE001 - the stream must survive
            logger.warning("Automatic order monitor error: %s", exc)
            return

        for event in events:
            await self._manager.broadcast(event, symbol=symbol)

    async def _handle_failure(self, exc: Exception, *, symbol: str | None = None) -> None:
        self.error_count += 1
        self.last_error = f"{type(exc).__name__}: {exc}"
        logger.warning("Price stream error (%s): %s", symbol or "-", self.last_error)
        await self._manager.broadcast(
            {
                "type": "error",
                "data": {
                    "message": "Upstream market data is unavailable.",
                    "detail": self.last_error,
                    "symbol": symbol,
                    "timestamp": datetime.now(tz=UTC).isoformat(),
                },
            },
            symbol=symbol,
        )

    def build_tick(self, quote: Quote) -> dict[str, Any]:
        """Shape a quote into the wire payload.

        Where the provider carries no depth, the bid and ask are derived from
        the configured spread model and labelled ``modelled`` -- synthetic
        numbers are never passed off as a real order book.
        """
        bid, ask = quote.bid, quote.ask
        source = BidAskSource.PROVIDER

        if bid is None or ask is None:
            if self._model_bid_ask:
                derived = self._spread.quote(quote.last_price)
                bid, ask = derived.bid, derived.ask
                source = BidAskSource.MODELLED
            else:
                source = BidAskSource.UNAVAILABLE

        change = None
        change_percent = None
        if quote.previous_close:
            change = to_money(quote.last_price - quote.previous_close)
            change_percent = (
                (change / quote.previous_close * Decimal("100")).quantize(
                    Decimal("0.01")
                )
                if quote.previous_close
                else None
            )

        capabilities = self._provider.capabilities
        return {
            "type": "tick",
            "data": {
                "symbol": quote.symbol,
                "exchange": quote.exchange,
                "last_price": str(quote.last_price),
                "bid": str(bid) if bid is not None else None,
                "ask": str(ask) if ask is not None else None,
                "bid_ask_source": source.value,
                "volume": quote.volume,
                "timestamp": quote.timestamp.isoformat(),
                "previous_close": (
                    str(quote.previous_close) if quote.previous_close else None
                ),
                "day_open": str(quote.day_open) if quote.day_open else None,
                "day_high": str(quote.day_high) if quote.day_high else None,
                "day_low": str(quote.day_low) if quote.day_low else None,
                "change": str(change) if change is not None else None,
                "change_percent": (
                    str(change_percent) if change_percent is not None else None
                ),
                "currency": quote.currency,
                "provider": quote.provider,
                "is_mock": capabilities.is_mock,
                "is_delayed": quote.is_delayed,
                "mode": self.mode.value,
                "server_time": datetime.now(tz=UTC).isoformat(),
            },
        }


# -- process-wide instances ----------------------------------------------

_manager: ConnectionManager | None = None
_service: PriceStreamService | None = None


def get_connection_manager() -> ConnectionManager:
    global _manager
    if _manager is None:
        _manager = ConnectionManager(
            max_connections=settings.STREAM_MAX_CONNECTIONS
        )
    return _manager


def get_price_stream() -> PriceStreamService:
    global _service
    if _service is None:
        from app.market_data.registry import get_provider

        _service = PriceStreamService(
            # The equity feed is the default; per-asset-class routing below
            # sends a crypto symbol to the crypto feed instead.
            provider=get_provider(),
            manager=get_connection_manager(),
            symbol=settings.TRADING_SYMBOL,
            exchange=settings.TRADING_EXCHANGE,
            poll_interval_seconds=settings.STREAM_POLL_INTERVAL_SECONDS,
            model_bid_ask=settings.STREAM_MODEL_BID_ASK,
            route_by_asset_class=True,
        )
    return _service


async def shutdown_price_stream() -> None:
    """Stop the stream and close every client. Called on application shutdown."""
    global _service, _manager
    if _service is not None:
        await _service.stop()
        _service = None
    if _manager is not None:
        await _manager.disconnect_all()
        _manager = None
