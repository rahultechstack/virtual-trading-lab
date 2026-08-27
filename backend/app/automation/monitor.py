"""Automatic order monitor.

    price tick -> evaluate ACTIVE triggers -> claim -> TradingEngine -> event

The monitor is the only thing that fires an automatic order, and it does not
execute anything itself: a fired trigger is handed to the ordinary
``TradingEngine.place_order``, so it produces the same Order, Trade, Position,
Wallet and PortfolioSnapshot rows a manual order does. There is exactly one
execution path in this system.

**Duplicate protection.** Firing is a two-phase claim:

1. Lock the ACTIVE row with ``SELECT ... FOR UPDATE SKIP LOCKED``, re-check the
   status under the lock, stamp it ``TRIGGERED`` and **commit**. That single
   committed transition is the claim -- any concurrent evaluation now sees a
   non-ACTIVE row and skips it.
2. Only then execute. The row is already out of the ACTIVE set, so a price that
   stays past the trigger across many ticks cannot fire it again.

Execution failures land in ``FAILED`` rather than reverting to ``ACTIVE``: an
order the engine refuses (no position left, no cash) would otherwise retry on
every tick forever.

An in-process ``asyncio.Lock`` additionally stops two overlapping evaluations
when execution takes longer than the poll interval.
"""

import asyncio
from datetime import UTC, datetime
from decimal import Decimal
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import async_sessionmaker

from app.automation.evaluator import condition_is_met
from app.core.config import settings
from app.core.exceptions import TradingError
from app.core.logging import get_logger
from app.db.session import SessionLocal
from app.models.automatic_order import AutomaticOrder, AutomaticOrderStatus

logger = get_logger(__name__)

#: Re-count ACTIVE orders at least this often, even while the cached count says
#: there are none. Guards against a row inserted outside this process (psql, a
#: second worker) never being noticed.
REVALIDATE_EVERY_EVALUATIONS = 20


class AutomaticOrderMonitor:
    """Evaluates ACTIVE automatic orders against each new price."""

    def __init__(self, session_factory: async_sessionmaker | None = None) -> None:
        self._session_factory = session_factory or SessionLocal
        self._lock = asyncio.Lock()
        #: How many ACTIVE orders exist, or None when that is unknown. With
        #: none, a tick costs nothing at all -- no session, no query. Without
        #: this the monitor opened a database connection on every single tick.
        self._active_count: int | None = None
        self._since_revalidate = 0
        #: Counters surfaced by the stream status endpoint.
        self.evaluations = 0
        self.triggered = 0
        self.failed = 0

    def invalidate(self) -> None:
        """Forget the cached ACTIVE count.

        Called when an automatic order is created or cancelled, so the very
        next tick re-reads instead of waiting for the periodic revalidation.
        """
        self._active_count = None

    async def on_price(
        self, *, market_price: Decimal, symbol: str | None = None
    ) -> list[dict[str, Any]]:
        """Evaluate every ACTIVE order against ``market_price``.

        Returns WebSocket-ready events for whatever fired. Never raises: a
        failure here must not take down the price stream.
        """
        if self._lock.locked():
            # A previous evaluation is still executing. Skipping is correct --
            # the next tick re-evaluates from committed state.
            return []

        async with self._lock:
            try:
                if not await self._has_active_orders():
                    return []
                return await self._evaluate(
                    market_price=market_price,
                    symbol=symbol or settings.TRADING_SYMBOL,
                )
            except Exception as exc:  # noqa: BLE001 - the stream must survive
                logger.warning("Automatic order evaluation failed: %s", exc)
                return []

    # -- internals -------------------------------------------------------

    async def _has_active_orders(self) -> bool:
        """Cheap gate: is there anything to evaluate at all?

        The overwhelmingly common case is an account with no standing orders,
        where this avoids a database round trip on every price tick.
        """
        self._since_revalidate += 1
        stale = (
            self._active_count is None
            or self._since_revalidate >= REVALIDATE_EVERY_EVALUATIONS
        )
        if stale:
            async with self._session_factory() as session:
                count = (
                    await session.execute(
                        select(func.count(AutomaticOrder.id)).where(
                            AutomaticOrder.status == AutomaticOrderStatus.ACTIVE
                        )
                    )
                ).scalar_one()
            self._active_count = int(count)
            self._since_revalidate = 0
        return (self._active_count or 0) > 0

    async def _evaluate(
        self, *, market_price: Decimal, symbol: str
    ) -> list[dict[str, Any]]:
        self.evaluations += 1
        events: list[dict[str, Any]] = []

        # Fire one at a time and re-read between each: executing the first can
        # change the position (and so retire the rest via reconciliation), so a
        # batch claimed up front would act on stale state.
        while True:
            claimed = await self._claim_next(market_price=market_price, symbol=symbol)
            if claimed is None:
                break
            events.append(await self._execute(claimed, market_price))

        # Firing changes how many remain, and reconciliation may have retired
        # others in the same transaction.
        if events:
            self.invalidate()

        return events

    async def _claim_next(
        self, *, market_price: Decimal, symbol: str
    ) -> int | None:
        """Lock, verify and stamp the next matching order. Returns its id.

        The claim is committed before execution, which is what makes duplicate
        firing impossible.
        """
        async with self._session_factory() as session:
            result = await session.execute(
                select(AutomaticOrder)
                .where(
                    AutomaticOrder.symbol == symbol,
                    AutomaticOrder.status == AutomaticOrderStatus.ACTIVE,
                )
                .order_by(AutomaticOrder.id.asc())
                .with_for_update(skip_locked=True)
            )

            for order in result.scalars():
                if not condition_is_met(
                    condition=order.trigger_condition,
                    trigger_price=order.trigger_price,
                    market_price=market_price,
                ):
                    continue

                order.status = AutomaticOrderStatus.TRIGGERED
                order.triggered_at = datetime.now(tz=UTC)
                order.trigger_market_price = market_price
                await session.commit()

                self.triggered += 1
                logger.info(
                    "Automatic order %s claimed at %s (%s %s).",
                    order.id,
                    market_price,
                    order.trigger_condition,
                    order.trigger_price,
                )
                return order.id

        return None

    async def _execute(
        self, automatic_order_id: int, market_price: Decimal
    ) -> dict[str, Any]:
        """Run a claimed order through the ordinary trading engine."""
        # Imported here rather than at module scope: the engine imports this
        # package back for reconciliation.
        from app.trading.engine import TradingEngine

        async with self._session_factory() as session:
            order = await session.get(AutomaticOrder, automatic_order_id)
            if order is None:  # pragma: no cover - defensive
                return self._event("failed", automatic_order_id, None)

            try:
                result = await TradingEngine(session).place_order(
                    side=order.action,
                    quantity=order.quantity,
                    reference_price=market_price,
                    symbol=order.symbol,
                )
            except TradingError as exc:
                # The engine refused it. Terminal, so it cannot spin.
                order.status = AutomaticOrderStatus.FAILED
                order.reason = exc.message[:500]
                await session.commit()
                await session.refresh(order)
                self.failed += 1
                logger.warning(
                    "Automatic order %s failed to execute: %s", order.id, exc.message
                )
                return self._event("failed", order.id, order)

            order.triggered_order_id = result.order.id
            await session.commit()
            await session.refresh(order)

            logger.info(
                "Automatic order %s executed as order %s: %s %s @ %s, net %s",
                order.id,
                result.order.id,
                order.action,
                order.quantity,
                result.order.execution_price,
                result.net_pnl,
            )
            return self._event("triggered", order.id, order, result)

    @staticmethod
    def _event(
        event: str,
        automatic_order_id: int,
        order: AutomaticOrder | None,
        result: Any | None = None,
    ) -> dict[str, Any]:
        """Shape the WebSocket frame for a fired or failed trigger."""
        data: dict[str, Any] = {
            "event": event,
            "automatic_order_id": automatic_order_id,
            "server_time": datetime.now(tz=UTC).isoformat(),
        }
        if order is not None:
            data.update(
                {
                    "order_type": order.order_type.value,
                    "trigger_condition": order.trigger_condition.value,
                    "trigger_price": str(order.trigger_price),
                    "action": order.action.value,
                    "quantity": order.quantity,
                    "status": order.status.value,
                    "symbol": order.symbol,
                    "reason": order.reason,
                    "trigger_market_price": (
                        str(order.trigger_market_price)
                        if order.trigger_market_price is not None
                        else None
                    ),
                    "triggered_order_id": order.triggered_order_id,
                }
            )
        if result is not None:
            data.update(
                {
                    "execution_price": str(result.order.execution_price),
                    "net_pnl": str(result.net_pnl),
                    "total_charges": str(result.total_charges),
                    "position_after": result.position.quantity,
                }
            )
        return {"type": "automatic_order", "data": data}

    def status(self) -> dict[str, Any]:
        """Counters for the stream status endpoint."""
        return {
            "evaluations": self.evaluations,
            "triggered": self.triggered,
            "failed": self.failed,
            "active_cached": self._active_count,
        }


# -- process-wide instance ------------------------------------------------

_monitor: AutomaticOrderMonitor | None = None


def get_automatic_order_monitor() -> AutomaticOrderMonitor:
    global _monitor
    if _monitor is None:
        _monitor = AutomaticOrderMonitor()
    return _monitor


def reset_automatic_order_monitor() -> None:
    """Drop the singleton. Used by tests and on shutdown."""
    global _monitor
    _monitor = None
