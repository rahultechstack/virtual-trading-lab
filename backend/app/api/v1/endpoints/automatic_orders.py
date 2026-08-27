"""Automatic order endpoints -- transport only.

The service holds every rule; these functions translate HTTP to service calls
and back. Whether a trigger fires is decided by the backend monitor, never by
a caller.
"""

from decimal import Decimal
from typing import Annotated

from fastapi import APIRouter, Query, status

from app.api.deps import DbSession
from app.core.config import settings
from app.automation.service import AutomaticOrderService
from app.models.automatic_order import AutomaticOrderStatus
from app.schemas.automatic_order import (
    AutomaticOrderResponse,
    CreateAutomaticOrderRequest,
)

router = APIRouter(prefix="/automatic-orders", tags=["automatic-orders"])


def _live_price() -> Decimal | None:
    """The stream's most recent tick price, when there is one.

    Used to reject a stop-loss that would fire on the next tick. Read here in
    the transport layer rather than in the service, so the service stays
    independent of the market-data stack -- the same rule the trading engine
    follows.
    """
    from app.realtime.price_stream import get_price_stream

    tick = get_price_stream().last_tick
    if tick is None:
        return None
    try:
        return Decimal(tick["data"]["last_price"])
    except (KeyError, TypeError, ArithmeticError):  # pragma: no cover - defensive
        return None


@router.post(
    "",
    response_model=AutomaticOrderResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Create a stop-loss or price trigger",
    responses={
        400: {
            "description": (
                "Invalid trigger, or a stop-loss that contradicts the open position."
            )
        }
    },
)
async def create_automatic_order(
    session: DbSession, payload: CreateAutomaticOrderRequest
) -> AutomaticOrderResponse:
    """Register a standing instruction.

    A ``STOP_LOSS`` is checked against the open position: direction, condition
    and quantity must all be consistent with it. A ``PRICE_TRIGGER`` is a free
    condition and is only checked for basic sanity.
    """
    order = await AutomaticOrderService(session).create(
        order_type=payload.order_type,
        trigger_price=payload.trigger_price,
        trigger_condition=payload.trigger_condition,
        action=payload.action,
        quantity=payload.quantity,
        symbol=payload.symbol,
        reference_price=payload.reference_price or _live_price(),
    )
    return AutomaticOrderResponse.model_validate(order)


@router.get(
    "/active",
    response_model=list[AutomaticOrderResponse],
    summary="Active automatic orders",
)
async def list_active_automatic_orders(
    session: DbSession,
    limit: Annotated[
        int, Query(ge=1, le=settings.MAX_HISTORY_PAGE_SIZE)
    ] = settings.DEFAULT_HISTORY_PAGE_SIZE,
) -> list[AutomaticOrderResponse]:
    """Oldest first -- the order the monitor evaluates them in."""
    orders = await AutomaticOrderService(session).list_active(limit=limit)
    return [AutomaticOrderResponse.model_validate(order) for order in orders]


@router.get(
    "",
    response_model=list[AutomaticOrderResponse],
    summary="Automatic order history",
)
async def list_automatic_orders(
    session: DbSession,
    limit: Annotated[
        int, Query(ge=1, le=settings.MAX_HISTORY_PAGE_SIZE)
    ] = settings.DEFAULT_HISTORY_PAGE_SIZE,
    offset: Annotated[int, Query(ge=0)] = 0,
    order_status: Annotated[
        AutomaticOrderStatus | None, Query(alias="status", description="Filter by status.")
    ] = None,
) -> list[AutomaticOrderResponse]:
    """Newest first. Includes triggered, cancelled and failed orders."""
    orders = await AutomaticOrderService(session).list_history(
        limit=limit, offset=offset, status=order_status
    )
    return [AutomaticOrderResponse.model_validate(order) for order in orders]


@router.get(
    "/{automatic_order_id}",
    response_model=AutomaticOrderResponse,
    summary="Get one automatic order",
    responses={404: {"description": "No automatic order with that id."}},
)
async def get_automatic_order(
    session: DbSession, automatic_order_id: int
) -> AutomaticOrderResponse:
    order = await AutomaticOrderService(session).get(automatic_order_id)
    return AutomaticOrderResponse.model_validate(order)


@router.post(
    "/{automatic_order_id}/cancel",
    response_model=AutomaticOrderResponse,
    summary="Cancel an active automatic order",
    responses={
        400: {"description": "The order has already triggered, failed or been cancelled."},
        404: {"description": "No automatic order with that id."},
    },
)
async def cancel_automatic_order(
    session: DbSession, automatic_order_id: int
) -> AutomaticOrderResponse:
    """Only an ACTIVE order can be cancelled; a fired one is history."""
    order = await AutomaticOrderService(session).cancel(automatic_order_id)
    return AutomaticOrderResponse.model_validate(order)
