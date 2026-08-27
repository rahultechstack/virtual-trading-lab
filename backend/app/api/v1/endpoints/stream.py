"""Live price WebSocket.

Clients connect to ``/api/v1/stream/prices`` and receive:

* ``{"type": "status", ...}``  once on connect -- provider, mode, mock flag
* ``{"type": "tick",   ...}``  on every price update
* ``{"type": "error",  ...}``  when the upstream feed fails
* ``{"type": "pong",   ...}``  in reply to a client ``ping``

Client messages:

* ``{"type": "ping"}``                     heartbeat
* ``{"type": "subscribe",   "symbol": X}`` watch X *instead of* whatever was
  being watched -- switching instruments is a replace, so a user browsing
  several stocks never accumulates subscriptions
* ``{"type": "unsubscribe", "symbol": X}`` stop watching X

The socket remains read-only for market data: no client message can place an
order. Reconnection is the client's job -- the server drops a dead socket
cleanly and the frontend hook backs off and redials.
"""

from datetime import UTC, datetime

from fastapi import APIRouter, WebSocket, WebSocketDisconnect

from app.core.exceptions import UnsupportedSymbolError
from app.core.config import settings
from app.core.logging import get_logger
from app.market_data.instruments import resolve_instrument
from app.realtime.connection_manager import ConnectionLimitReached
from app.realtime.price_stream import get_connection_manager, get_price_stream

logger = get_logger(__name__)

router = APIRouter(prefix="/stream", tags=["stream"])

#: Close code for a policy refusal (RFC 6455).
_POLICY_VIOLATION = 1008



async def _switch_symbol(manager, service, websocket, symbol) -> None:
    """Point one client at one instrument.

    Validates against the supported universe here rather than trusting the
    client, confirms the switch, and replays the most recent tick so the chart
    is populated immediately instead of waiting a full poll interval.
    """
    try:
        instrument = resolve_instrument(symbol if isinstance(symbol, str) else None)
    except UnsupportedSymbolError as exc:
        await manager.send_to(
            websocket,
            {"type": "error", "data": {"message": exc.message, "fatal": False}},
        )
        return

    await manager.set_subscription(websocket, instrument.symbol)
    await manager.send_to(
        websocket,
        {
            "type": "subscription",
            "data": {
                "symbols": [instrument.symbol],
                "symbol": instrument.symbol,
                "exchange": instrument.exchange,
                "company_name": instrument.company_name,
                "server_time": datetime.now(tz=UTC).isoformat(),
            },
        },
    )

    cached = service.last_tick_for(instrument.symbol)
    if cached is not None:
        await manager.send_to(websocket, cached)


@router.get("/status", summary="Live-stream status")
async def stream_status() -> dict:
    """Report what the stream is doing and which provider is behind it.

    Check ``is_mock`` before trusting any price the socket delivers.
    """
    return get_price_stream().status()


@router.websocket("/prices")
async def price_stream(websocket: WebSocket) -> None:
    """Stream live quotes for the configured instrument to one client."""
    manager = get_connection_manager()
    service = get_price_stream()

    try:
        await manager.connect(websocket)
    except ConnectionLimitReached as exc:
        # accept() then close() so the client sees the reason rather than a
        # bare handshake failure.
        await websocket.accept()
        await websocket.send_json(
            {"type": "error", "data": {"message": str(exc), "fatal": True}}
        )
        await websocket.close(code=_POLICY_VIOLATION)
        logger.warning("Rejected a WebSocket client: %s", exc)
        return

    # Start the feed on the first listener rather than at boot, so an idle
    # server makes no upstream calls at all.
    if not service.is_running:
        await service.start()

    try:
        await manager.send_to(
            websocket,
            {
                "type": "status",
                "data": {
                    **service.status(),
                    "server_time": datetime.now(tz=UTC).isoformat(),
                },
            },
        )

        # Start on the configured default instrument, so a client that never
        # subscribes still receives prices.
        await _switch_symbol(manager, service, websocket, settings.TRADING_SYMBOL)

        while True:
            message = await websocket.receive_json()
            if not isinstance(message, dict):
                continue

            kind = message.get("type")

            if kind == "ping":
                await manager.send_to(
                    websocket,
                    {
                        "type": "pong",
                        "data": {"server_time": datetime.now(tz=UTC).isoformat()},
                    },
                )

            elif kind == "subscribe":
                await _switch_symbol(
                    manager, service, websocket, message.get("symbol")
                )

            elif kind == "unsubscribe":
                symbol = message.get("symbol")
                if isinstance(symbol, str):
                    await manager.unsubscribe(websocket, symbol)
                    await manager.send_to(
                        websocket,
                        {
                            "type": "subscription",
                            "data": {
                                "symbols": sorted(
                                    manager.subscriptions_for(websocket)
                                ),
                                "server_time": datetime.now(tz=UTC).isoformat(),
                            },
                        },
                    )

    except WebSocketDisconnect:
        await manager.disconnect(websocket)
    except Exception as exc:  # noqa: BLE001 - one client must not take others down
        logger.debug("WebSocket client error: %s", exc)
        await manager.close(websocket)
