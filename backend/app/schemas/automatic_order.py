"""Automatic order API contracts.

Monetary values serialise as JSON strings carrying ``Decimal``, consistent with
every other schema in the project.
"""

from datetime import datetime
from decimal import Decimal

from pydantic import BaseModel, ConfigDict, Field

from app.schemas.common import Quantity

from app.models.automatic_order import (
    AutomaticOrderStatus,
    AutomaticOrderType,
    TriggerCondition,
)
from app.core.config import settings
from app.market_data.instruments import AssetClass
from app.models.enums import OrderSide

_MONEY = {"max_digits": 18, "decimal_places": 2}
#: Fractional, so a stop-loss can protect 0.001 BTC. The instrument decides how
#: finely, not this schema -- see the note in schemas/trading.py.
_QUANTITY = {"max_digits": 28}


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
    quantity: Decimal = Field(
        gt=0,
        le=settings.MAX_ORDER_QUANTITY,
        description=(
            "Positive size. Whole units for a stock; fractional for crypto. "
            'Send it as a string ("0.001") to avoid float rounding.'
        ),
        **_QUANTITY,
    )
    symbol: str | None = Field(
        default=None,
        description="Any supported instrument. Defaults to the configured default.",
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
    asset_class: AssetClass
    order_type: AutomaticOrderType
    trigger_price: Decimal
    trigger_condition: TriggerCondition
    action: OrderSide
    quantity: Quantity
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
