"""Automatic order service.

Owns creation, validation, listing, cancellation and -- importantly --
*reconciliation* against the position whenever a fill moves it.

It never executes anything. Firing is the monitor's job, and the monitor hands
execution to the ordinary ``TradingEngine``.
"""

from datetime import UTC, datetime
from decimal import Decimal

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.automation.evaluator import (
    closing_side_for,
    protects_position,
    stop_loss_condition_for,
)
from app.core.config import settings
from app.core.exceptions import (
    AutomaticOrderNotFoundError,
    InvalidAutomaticOrderError,
    UnsupportedSymbolError,
)
from app.core.logging import get_logger
from app.models.automatic_order import (
    AutomaticOrder,
    AutomaticOrderStatus,
    AutomaticOrderType,
    TriggerCondition,
)
from app.models.enums import OrderSide
from app.models.trading import MAX_ORDER_QUANTITY, Position

logger = get_logger(__name__)

#: Reasons recorded on the row when the service retires an order itself.
REASON_POSITION_CLOSED = "Position closed; the stop-loss no longer protects anything."
REASON_POSITION_REVERSED = "Position reversed direction; the stop-loss no longer applies."
REASON_USER_CANCELLED = "Cancelled by the user."


class AutomaticOrderService:
    """Create, validate, list, cancel and reconcile automatic orders."""

    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    # -- creation --------------------------------------------------------

    async def create(
        self,
        *,
        order_type: AutomaticOrderType,
        trigger_price: Decimal,
        trigger_condition: TriggerCondition,
        action: OrderSide,
        quantity: int,
        symbol: str | None = None,
        reference_price: Decimal | None = None,
        commit: bool = True,
    ) -> AutomaticOrder:
        """Validate and persist a new ACTIVE automatic order.

        Args:
            reference_price: Current market price, when the caller has one. Used
                only to reject a stop that would fire on the very next tick.
                Omitted, the directional rules are still enforced.

        Raises:
            UnsupportedSymbolError: symbol other than the configured instrument.
            InvalidAutomaticOrderError: any validation rule below.
        """
        resolved = self._resolve_symbol(symbol)
        self._validate_basics(quantity=quantity, trigger_price=trigger_price)

        if order_type is AutomaticOrderType.STOP_LOSS:
            await self._validate_stop_loss(
                symbol=resolved,
                trigger_price=trigger_price,
                trigger_condition=trigger_condition,
                action=action,
                quantity=quantity,
                reference_price=reference_price,
            )

        order = AutomaticOrder(
            symbol=resolved,
            exchange=settings.TRADING_EXCHANGE,
            order_type=order_type,
            trigger_price=trigger_price,
            trigger_condition=trigger_condition,
            action=action,
            quantity=quantity,
            status=AutomaticOrderStatus.ACTIVE,
        )
        self._session.add(order)
        await self._session.flush()
        if commit:
            await self._session.commit()
            await self._session.refresh(order)

        logger.info(
            "Automatic order %s created: %s %s %s -> %s %s",
            order.id,
            order.order_type,
            order.trigger_condition,
            order.trigger_price,
            order.action,
            order.quantity,
        )
        return order

    # -- validation ------------------------------------------------------

    @staticmethod
    def _resolve_symbol(symbol: str | None) -> str:
        if symbol is None:
            return settings.TRADING_SYMBOL
        if symbol.strip().upper() != settings.TRADING_SYMBOL.upper():
            raise UnsupportedSymbolError(
                f"This platform trades {settings.TRADING_EXCHANGE}:"
                f"{settings.TRADING_SYMBOL} only. Received '{symbol}'."
            )
        return settings.TRADING_SYMBOL

    @staticmethod
    def _validate_basics(*, quantity: int, trigger_price: Decimal) -> None:
        if quantity <= 0:
            raise InvalidAutomaticOrderError(
                f"Quantity must be positive, got {quantity}."
            )
        if quantity > MAX_ORDER_QUANTITY:
            raise InvalidAutomaticOrderError(
                f"Quantity {quantity} exceeds the maximum of {MAX_ORDER_QUANTITY}."
            )
        if trigger_price <= 0:
            raise InvalidAutomaticOrderError(
                f"Trigger price must be positive, got {trigger_price}."
            )

    async def _validate_stop_loss(
        self,
        *,
        symbol: str,
        trigger_price: Decimal,
        trigger_condition: TriggerCondition,
        action: OrderSide,
        quantity: int,
        reference_price: Decimal | None,
    ) -> None:
        """Enforce that a stop-loss actually protects the open position.

        A long can only be stopped out downwards by a SELL; a short only
        upwards by a BUY_TO_COVER. The direction is derived from the position
        rather than trusted from the request, so the frontend cannot invent a
        combination the engine would later reject.
        """
        position = await self._position(symbol)
        quantity_held = position.quantity if position else 0

        if quantity_held == 0:
            raise InvalidAutomaticOrderError(
                "A stop-loss needs an open position to protect, but the "
                "position is flat. Use a PRICE_TRIGGER for an entry condition."
            )

        expected_action = closing_side_for(quantity_held)
        if action is not expected_action:
            direction = "long" if quantity_held > 0 else "short"
            raise InvalidAutomaticOrderError(
                f"A stop-loss on a {direction} position of {quantity_held} must "
                f"act with {expected_action}, not {action}."
            )

        expected_condition = stop_loss_condition_for(quantity_held)
        if trigger_condition is not expected_condition:
            direction = "long" if quantity_held > 0 else "short"
            raise InvalidAutomaticOrderError(
                f"A stop-loss on a {direction} position triggers on "
                f"{expected_condition} (it stops you out as the price moves "
                f"against you), not {trigger_condition}."
            )

        held = abs(quantity_held)
        if quantity > held:
            raise InvalidAutomaticOrderError(
                f"Cannot stop out {quantity}; the position is only {held}."
            )

        # Only a live price can tell us the stop is on the correct side *now*.
        # Entry price is deliberately not used: a stop above entry is a valid
        # profit-protecting stop once the trade has moved in your favour.
        if reference_price is None:
            return

        if quantity_held > 0 and trigger_price >= reference_price:
            raise InvalidAutomaticOrderError(
                f"A stop-loss on a long must sit below the current price. "
                f"Trigger {trigger_price} is not below {reference_price}; it "
                "would fire immediately."
            )
        if quantity_held < 0 and trigger_price <= reference_price:
            raise InvalidAutomaticOrderError(
                f"A stop-loss on a short must sit above the current price. "
                f"Trigger {trigger_price} is not above {reference_price}; it "
                "would fire immediately."
            )

    # -- reads -----------------------------------------------------------

    async def _position(self, symbol: str) -> Position | None:
        result = await self._session.execute(
            select(Position).where(Position.symbol == symbol)
        )
        return result.scalar_one_or_none()

    async def get(self, automatic_order_id: int) -> AutomaticOrder:
        result = await self._session.execute(
            select(AutomaticOrder).where(AutomaticOrder.id == automatic_order_id)
        )
        order = result.scalar_one_or_none()
        if order is None:
            raise AutomaticOrderNotFoundError(
                f"Automatic order {automatic_order_id} does not exist."
            )
        return order

    async def _get_for_update(self, automatic_order_id: int) -> AutomaticOrder:
        """Row-locked read that refreshes any stale copy in the session.

        ``populate_existing`` matters: with ``expire_on_commit=False`` an object
        already in the identity map would otherwise keep the status it had when
        first loaded, hiding a concurrent claim by the monitor.
        """
        result = await self._session.execute(
            select(AutomaticOrder)
            .where(AutomaticOrder.id == automatic_order_id)
            .with_for_update()
            .execution_options(populate_existing=True)
        )
        order = result.scalar_one_or_none()
        if order is None:
            raise AutomaticOrderNotFoundError(
                f"Automatic order {automatic_order_id} does not exist."
            )
        return order

    async def list_active(self, *, limit: int = 100) -> list[AutomaticOrder]:
        """Every ACTIVE order, oldest first -- the order the monitor fires them in."""
        result = await self._session.execute(
            select(AutomaticOrder)
            .where(AutomaticOrder.status == AutomaticOrderStatus.ACTIVE)
            .order_by(AutomaticOrder.id.asc())
            .limit(limit)
        )
        return list(result.scalars().all())

    async def list_history(
        self,
        *,
        limit: int = 100,
        offset: int = 0,
        status: AutomaticOrderStatus | None = None,
    ) -> list[AutomaticOrder]:
        """Newest first. Includes ACTIVE unless filtered."""
        query = (
            select(AutomaticOrder)
            .order_by(AutomaticOrder.id.desc())
            .limit(limit)
            .offset(offset)
        )
        if status is not None:
            query = query.where(AutomaticOrder.status == status)
        result = await self._session.execute(query)
        return list(result.scalars().all())

    # -- cancellation ----------------------------------------------------

    async def cancel(
        self, automatic_order_id: int, *, reason: str = REASON_USER_CANCELLED
    ) -> AutomaticOrder:
        """Cancel an ACTIVE order.

        The row is taken with ``SELECT ... FOR UPDATE`` and re-read from the
        database rather than trusted from the session's identity map, because
        the monitor may have claimed it from another session a moment ago.
        Without that, a cancel racing a trigger could overwrite TRIGGERED.

        Raises:
            AutomaticOrderNotFoundError: no order with that id.
            InvalidAutomaticOrderError: the order has already reached a
                terminal status. Cancelling a fired order would rewrite history.
        """
        order = await self._get_for_update(automatic_order_id)
        if not order.is_active:
            raise InvalidAutomaticOrderError(
                f"Automatic order {automatic_order_id} is {order.status} and can "
                "no longer be cancelled."
            )

        self._mark_cancelled(order, reason)
        await self._session.commit()
        await self._session.refresh(order)
        logger.info("Automatic order %s cancelled: %s", order.id, reason)
        return order

    @staticmethod
    def _mark_cancelled(order: AutomaticOrder, reason: str) -> None:
        order.status = AutomaticOrderStatus.CANCELLED
        order.cancelled_at = datetime.now(tz=UTC)
        order.reason = reason[:500]

    # -- reconciliation --------------------------------------------------

    async def reconcile_for_position(
        self, *, symbol: str, position_quantity: int
    ) -> list[AutomaticOrder]:
        """Realign stop-losses after a fill moved the position.

        Called from inside ``TradingEngine.place_order``'s transaction, so the
        position and its stop-losses can never disagree, even for a moment.

        Three cases:

        1. **Position flat or reversed** -- the stop no longer protects
           anything, so it is CANCELLED with a reason.
        2. **Position reduced below the stop's quantity** -- the quantity is
           *clamped* down to what is left. Chosen over cancelling because the
           user's intent ("get me out of this position") survives a partial
           exit; cancelling would silently leave the remainder unprotected.
        3. **Position grew** -- left alone. Raising the quantity would protect
           shares the user never asked to protect.

        PRICE_TRIGGER orders are untouched: they are entry/exit conditions in
        their own right, not attached to a position.

        Returns the orders it changed, for the caller to broadcast.
        """
        result = await self._session.execute(
            select(AutomaticOrder)
            .where(
                AutomaticOrder.symbol == symbol,
                AutomaticOrder.status == AutomaticOrderStatus.ACTIVE,
                AutomaticOrder.order_type == AutomaticOrderType.STOP_LOSS,
            )
            .with_for_update()
        )
        stops = list(result.scalars().all())
        if not stops:
            return []

        changed: list[AutomaticOrder] = []
        held = abs(position_quantity)

        for stop in stops:
            if not protects_position(stop.action, position_quantity):
                reason = (
                    REASON_POSITION_CLOSED
                    if position_quantity == 0
                    else REASON_POSITION_REVERSED
                )
                self._mark_cancelled(stop, reason)
                changed.append(stop)
                logger.info("Automatic order %s retired: %s", stop.id, reason)
                continue

            if stop.quantity > held:
                logger.info(
                    "Automatic order %s clamped from %s to %s (position reduced).",
                    stop.id,
                    stop.quantity,
                    held,
                )
                stop.quantity = held
                changed.append(stop)

        if changed:
            await self._session.flush()
        return changed
