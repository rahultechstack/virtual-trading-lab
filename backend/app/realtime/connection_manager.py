"""WebSocket connection manager.

Owns the set of live client connections and the fan-out to them. It knows
nothing about market data -- it moves JSON payloads to whoever is listening.

Three things it has to get right:

* **A slow or dead client must not stall the others.** Sends run concurrently
  and each is isolated, so one broken socket cannot block the broadcast.
* **Dead connections must be reaped.** A send that raises drops that client
  from the pool rather than leaving a corpse to fail on every future tick.
* **The set must not be mutated while it is being iterated.** All membership
  changes happen under a lock, and broadcasts iterate a snapshot.
"""

import asyncio
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any

from fastapi import WebSocket
from starlette.websockets import WebSocketState

from app.core.logging import get_logger

logger = get_logger(__name__)


class ConnectionLimitReached(Exception):
    """Raised when the pool is already at its configured capacity."""


@dataclass
class ConnectionStats:
    """Counters for the stream status endpoint."""

    total_accepted: int = 0
    total_rejected: int = 0
    total_disconnected: int = 0
    messages_sent: int = 0
    send_failures: int = 0
    started_at: datetime = field(default_factory=lambda: datetime.now(tz=UTC))


class ConnectionManager:
    """Tracks connected clients and broadcasts to them."""

    def __init__(self, *, max_connections: int = 50) -> None:
        self._connections: set[WebSocket] = set()
        self._lock = asyncio.Lock()
        self.max_connections = max_connections
        self.stats = ConnectionStats()

    # -- membership ------------------------------------------------------

    @property
    def connection_count(self) -> int:
        return len(self._connections)

    @property
    def has_listeners(self) -> bool:
        """Whether anyone is listening.

        The price stream uses this to stop polling the upstream provider when
        nobody is connected, which keeps rate limits for when they matter.
        """
        return bool(self._connections)

    async def connect(self, websocket: WebSocket) -> None:
        """Accept a client and add it to the pool.

        Raises:
            ConnectionLimitReached: the pool is full. The caller is
                responsible for closing the socket with a suitable code.
        """
        async with self._lock:
            if len(self._connections) >= self.max_connections:
                self.stats.total_rejected += 1
                raise ConnectionLimitReached(
                    f"Refusing connection: {self.max_connections} clients already "
                    "connected."
                )

        await websocket.accept()

        async with self._lock:
            self._connections.add(websocket)
            self.stats.total_accepted += 1

        logger.info(
            "WebSocket client connected (%d active).", len(self._connections)
        )

    async def disconnect(self, websocket: WebSocket) -> None:
        """Remove a client from the pool. Safe to call more than once."""
        async with self._lock:
            was_present = websocket in self._connections
            self._connections.discard(websocket)

        if was_present:
            self.stats.total_disconnected += 1
            logger.info(
                "WebSocket client disconnected (%d active).", len(self._connections)
            )

    async def close(self, websocket: WebSocket, code: int = 1000) -> None:
        """Close a socket and drop it, ignoring an already-closed socket."""
        await self.disconnect(websocket)
        try:
            if websocket.client_state is not WebSocketState.DISCONNECTED:
                await websocket.close(code=code)
        except (RuntimeError, ConnectionError) as exc:  # pragma: no cover
            logger.debug("Ignoring error while closing a socket: %s", exc)

    async def disconnect_all(self, code: int = 1001) -> None:
        """Close every connection. Used on application shutdown."""
        async with self._lock:
            sockets = list(self._connections)
            self._connections.clear()

        for socket in sockets:
            try:
                if socket.client_state is not WebSocketState.DISCONNECTED:
                    await socket.close(code=code)
            except (RuntimeError, ConnectionError):  # pragma: no cover
                pass

        if sockets:
            logger.info("Closed %d WebSocket connection(s) on shutdown.", len(sockets))

    # -- sending ---------------------------------------------------------

    async def send_to(self, websocket: WebSocket, message: dict[str, Any]) -> bool:
        """Send to one client. Returns False and drops it on failure."""
        try:
            await websocket.send_json(message)
        except Exception as exc:  # noqa: BLE001 - any failure means it is gone
            self.stats.send_failures += 1
            logger.debug("Dropping a client after a failed send: %s", exc)
            await self.disconnect(websocket)
            return False

        self.stats.messages_sent += 1
        return True

    async def broadcast(self, message: dict[str, Any]) -> int:
        """Fan a message out to every client. Returns how many received it.

        Sends run concurrently so one slow client cannot hold up the rest, and
        any that fail are removed from the pool.
        """
        async with self._lock:
            targets = list(self._connections)

        if not targets:
            return 0

        results = await asyncio.gather(
            *(self.send_to(socket, message) for socket in targets),
            return_exceptions=True,
        )

        delivered = sum(1 for result in results if result is True)
        if delivered < len(targets):
            logger.debug(
                "Broadcast reached %d of %d clients.", delivered, len(targets)
            )
        return delivered
