"""Trading API contracts.

Monetary values serialise as JSON strings carrying ``Decimal``, consistent
with the wallet and market-data schemas.
"""

from datetime import datetime
from decimal import Decimal

from pydantic import BaseModel, ConfigDict, Field

from app.models.enums import OrderSide, OrderStatus, OrderType

_MONEY = {"max_digits": 18, "decimal_places": 2}


class PlaceOrderRequest(BaseModel):
    """An instruction to trade.

    ``execution_price`` is supplied by the caller in this stage. Live pricing
    arrives in a later stage; until then the engine has no opinion about what
    a fair fill price is.
    """

    side: OrderSide = Field(description="BUY, SELL, SHORT_SELL or BUY_TO_COVER.")
    quantity: int = Field(gt=0, le=10_000_000, description="Shares. Positive.")
    execution_price: Decimal = Field(
        gt=0, description="Price to fill at.", **_MONEY
    )
    requested_price: Decimal | None = Field(
        default=None,
        gt=0,
        description="Recorded for audit; does not affect the fill.",
        **_MONEY,
    )
    symbol: str | None = Field(
        default=None, description="Optional. Must be RELIANCE if supplied."
    )


class OrderResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    symbol: str
    exchange: str
    side: OrderSide
    order_type: OrderType
    quantity: int
    requested_price: Decimal | None
    execution_price: Decimal | None
    status: OrderStatus
    rejection_reason: str | None
    created_at: datetime
    filled_at: datetime | None


class TradeResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    order_id: int
    symbol: str
    exchange: str
    side: OrderSide
    quantity: int
    execution_price: Decimal
    realized_pnl: Decimal = Field(
        description="P&L this fill locked in. Zero for a fill that only opened."
    )
    closed_quantity: int
    created_at: datetime


class PositionResponse(BaseModel):
    """``quantity`` carries direction: >0 long, 0 flat, <0 short."""

    model_config = ConfigDict(from_attributes=True)

    symbol: str
    exchange: str
    quantity: int
    average_price: Decimal
    realized_pnl: Decimal
    updated_at: datetime | None = None


class OrderResultResponse(BaseModel):
    """Everything one accepted order produced."""

    order: OrderResponse
    trade: TradeResponse
    position: PositionResponse
    realized_pnl: Decimal
    cash_delta: Decimal = Field(
        description="Signed cash movement: negative for buys, positive for sells."
    )


class PortfolioResponse(BaseModel):
    """Account valuation.

    ``unrealized_pnl`` and ``position_value`` are zero unless a ``mark_price``
    was supplied -- the engine never fetches prices itself.
    """

    cash_balance: Decimal
    initial_balance: Decimal
    quantity: int
    average_price: Decimal
    realized_pnl: Decimal
    unrealized_pnl: Decimal
    position_value: Decimal
    total_equity: Decimal
    total_pnl: Decimal
    mark_price: Decimal | None
    currency: str
