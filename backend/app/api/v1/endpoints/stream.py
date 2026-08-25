"""Live price WebSocket.

Clients connect to ``/api/v1/stream/prices`` and receive:

* ``{"type": "status", ...}``  once on connect -- provider, mode, mock flag
* ``{"type": "tick",   ...}``  on every price update
* ``{"type": "error",  ...}``  when the upstream feed fails
* ``{"type": "pong",   ...}``  in reply to a client ``ping``

The socket is read-only for market data: the only client message understood is
a ``ping`` heartbeat. Reconnection is the client's job -- the server simply
drops a dead socket cleanly, and the frontend hook backs off and redials.
"""

from datetime import UTC, datetime

from fastapi import APIRouter, WebSocket, WebSocketDisconnect

from app.core.logging import get_logger
from app.realtime.connection_manager import ConnectionLimitReached
from app.realtime.price_stream import get_connection_manager, get_price_stream

logger = get_logger(__name__)

router = APIRouter(prefix="/stream", tags=["stream"])

#: Close code for a policy refusal (RFC 6455).
_POLICY_VIOLATION = 1008


@router.get("/status", summary="Live-stream status")
async def stream_status() -> dict:
    """Report what the stream is doing and which provider is behind it.

    Check ``is_mock`` before trusting any price the socket delivers.
    """
    return get_price_stream().status()


@router.websocket("/prices")
async def price_stream(websocket: WebSocket) -> None:
    """Stream live RELIANCE quotes to one client."""
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

        # A new client should see a price immediately rather than waiting a
        # full poll interval for the next tick.
        if service.last_tick is not None:
            await manager.send_to(websocket, service.last_tick)

        while True:
            message = await websocket.receive_json()
            if isinstance(message, dict) and message.get("type") == "ping":
                await manager.send_to(
                    websocket,
                    {
                        "type": "pong",
                        "data": {"server_time": datetime.now(tz=UTC).isoformat()},
                    },
                )

    except WebSocketDisconnect:
        await manager.disconnect(websocket)
    except Exception as exc:  # noqa: BLE001 - one client must not take others down
        logger.debug("WebSocket client error: %s", exc)
        await manager.close(websocket)
