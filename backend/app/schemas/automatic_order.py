"""Automatic order API contracts.

Monetary values serialise as JSON strings carrying ``Decimal``, consistent with
every other schema in the project.
"""

from datetime import datetime
from decimal import Decimal

from pydantic import BaseModel, ConfigDict, Field

from app.models.automatic_order import (
    AutomaticOrderStatus,
    AutomaticOrderType,
    TriggerCondition,
)
from app.models.enums import OrderSide

_MONEY = {"max_digits": 18, "decimal_places": 2}


class CreateAutomaticOrderRequest(BaseModel):
    """A standing instruction to trade when the price reaches a level.

    For a ``STOP_LOSS`` the backend derives what is valid from the open
    position: a long may only be stopped out by ``SELL`` on ``LTE``, a short
    only by ``BUY_TO_COVER`` on ``GTE``. Sending anything else is rejected --
    the frontend is never trusted to decide this.
    """

    order_type: AutomaticOrderType = Field(
        description="STOP_LOSS (validated against the open position) or PRICE_TRIGGER."
    )
    trigger_price: Decimal = Field(
        gt=0, description="Price level the market is compared against.", **_MONEY
    )
    trigger_condition: TriggerCondition = Field(
        description="GTE fires at or above the trigger, LTE at or below it."
    )
    action: OrderSide = Field(
        description="Side executed when it fires: BUY, SELL, SHORT_SELL or BUY_TO_COVER."
    )
    quantity: int = Field(gt=0, le=10_000_000, description="Shares. Positive.")
    symbol: str | None = Field(
        default=None, description="Optional. Must be the configured symbol if supplied."
    )
    reference_price: Decimal | None = Field(
        default=None,
        gt=0,
        description=(
            "Current market price. Optional -- when supplied, a stop-loss that "
            "would fire immediately is rejected. Omitted, the endpoint falls "
            "back to the live stream's most recent tick."
        ),
        **_MONEY,
    )


class AutomaticOrderResponse(BaseModel):
    """One automatic order."""

    model_config = ConfigDict(from_attributes=True)

    id: int
    symbol: str
    exchange: str
    order_type: AutomaticOrderType
    trigger_price: Decimal
    trigger_condition: TriggerCondition
    action: OrderSide
    quantity: int
    status: AutomaticOrderStatus

    created_at: datetime
    triggered_at: datetime | None = None
    cancelled_at: datetime | None = None

    trigger_market_price: Decimal | None = Field(
        default=None,
        description="Market price that satisfied the condition. Null until fired.",
    )
    triggered_order_id: int | None = Field(
        default=None, description="The order this produced, once it fired."
    )
    reason: str | None = Field(
        default=None, description="Why it was cancelled, or why execution failed."
    )
