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

    ``reference_price`` is a **mid** price. The actual execution price is
    derived from it by the spread and slippage models, both of which move it
    against you, so a fill is never better than the reference.
    """

    side: OrderSide = Field(description="BUY, SELL, SHORT_SELL or BUY_TO_COVER.")
    quantity: int = Field(gt=0, le=10_000_000, description="Shares. Positive.")
    reference_price: Decimal = Field(
        gt=0,
        description="Mid price to trade around; spread and slippage are applied to it.",
        **_MONEY,
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


class ChargesResponse(BaseModel):
    """Itemised charges, as on a contract note."""

    model_config = ConfigDict(from_attributes=True)

    brokerage: Decimal
    stt: Decimal = Field(description="Securities Transaction Tax.")
    exchange_charges: Decimal
    sebi_charges: Decimal
    stamp_duty: Decimal
    gst: Decimal
    dp_charges: Decimal
    total_charges: Decimal


class TradeResponse(BaseModel):
    """A fill priced end to end."""

    model_config = ConfigDict(from_attributes=True)

    id: int
    order_id: int
    symbol: str
    exchange: str
    side: OrderSide
    quantity: int

    reference_price: Decimal | None = Field(
        default=None, description="The mid price requested."
    )
    bid_price: Decimal | None = None
    ask_price: Decimal | None = None
    execution_price: Decimal = Field(
        description="Where it actually filled, after spread and slippage."
    )

    spread_cost: Decimal = Field(description="Money lost crossing the spread.")
    slippage_cost: Decimal = Field(description="Money lost to adverse movement.")

    brokerage: Decimal
    stt: Decimal
    exchange_charges: Decimal
    sebi_charges: Decimal
    stamp_duty: Decimal
    gst: Decimal
    dp_charges: Decimal
    total_charges: Decimal

    gross_pnl: Decimal = Field(
        description="P&L from price movement, before charges. Zero on an opening fill."
    )
    net_pnl: Decimal = Field(description="gross_pnl minus this fill's charges.")

    closed_quantity: int
    created_at: datetime


class PositionResponse(BaseModel):
    """``quantity`` carries direction: >0 long, 0 flat, <0 short."""

    model_config = ConfigDict(from_attributes=True)

    symbol: str
    exchange: str
    quantity: int
    average_price: Decimal
    realized_pnl: Decimal = Field(
        description="Cumulative P&L from price movement, before charges."
    )
    total_charges: Decimal = Field(description="Cumulative charges paid.")
    net_realized_pnl: Decimal = Field(
        description="realized_pnl minus total_charges."
    )
    updated_at: datetime | None = None


class OrderResultResponse(BaseModel):
    """Everything one accepted order produced."""

    order: OrderResponse
    trade: TradeResponse
    position: PositionResponse
    gross_pnl: Decimal = Field(
        description="P&L from price movement on this fill, before charges."
    )
    total_charges: Decimal = Field(description="Charges on this fill.")
    net_pnl: Decimal = Field(description="gross_pnl minus total_charges.")
    cash_delta: Decimal = Field(
        description="Signed cash movement, charges included."
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
    realized_pnl: Decimal = Field(description="Gross, before charges.")
    total_charges: Decimal
    net_realized_pnl: Decimal
    unrealized_pnl: Decimal
    position_value: Decimal
    total_equity: Decimal
    total_pnl: Decimal = Field(description="Gross realized plus unrealized.")
    net_total_pnl: Decimal = Field(
        description="Net realized plus unrealized - the figure after all costs."
    )
    mark_price: Decimal | None
    currency: str


class ExecutionCostPreview(BaseModel):
    """What an order would cost, without placing it.

    Lets a caller inspect the spread, slippage and charge model before
    committing to a trade.
    """

    side: OrderSide
    quantity: int
    reference_price: Decimal
    bid_price: Decimal
    ask_price: Decimal
    spread: Decimal = Field(description="Full quoted spread, ask minus bid.")
    execution_price: Decimal
    spread_cost: Decimal
    slippage_cost: Decimal
    charges: ChargesResponse
    total_execution_cost: Decimal = Field(
        description="Spread plus slippage plus charges."
    )
