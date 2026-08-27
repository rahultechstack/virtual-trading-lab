"""Trading API contracts.

Monetary values serialise as JSON strings carrying ``Decimal``, consistent
with the wallet and market-data schemas.
"""

from datetime import datetime
from decimal import Decimal

from pydantic import BaseModel, ConfigDict, Field

from app.schemas.common import Quantity

from app.market_data.instruments import AssetClass
from app.models.enums import OrderSide, OrderStatus, OrderType

_MONEY = {"max_digits": 18, "decimal_places": 2}
#: Quantities are Decimal, not int -- crypto trades fractionally. Serialised as
#: a JSON string like every other Decimal here, so no precision is lost in
#: transit.
#:
#: Deliberately NO ``decimal_places`` bound: how finely an instrument divides
#: is the instrument's business, and ``normalise_quantity`` answers it knowing
#: which instrument was asked for. A schema-level cap would reject a
#: sub-satoshi size with a 422 while a fractional *share* got a 400, splitting
#: one rule across two error families for no gain. ``max_digits`` stays as a
#: sanity bound on absurd input.
_QUANTITY = {"max_digits": 28}


class PlaceOrderRequest(BaseModel):
    """An instruction to trade.

    ``reference_price`` is a **mid** price. The actual execution price is
    derived from it by the spread and slippage models, both of which move it
    against you, so a fill is never better than the reference.
    """

    side: OrderSide = Field(description="BUY, SELL, SHORT_SELL or BUY_TO_COVER.")
    quantity: Decimal = Field(
        gt=0,
        le=10_000_000,
        description=(
            "Positive size. Whole units for a stock; fractional for crypto, "
            "down to the instrument's quantity_step. Send it as a string "
            '("0.001") to avoid float rounding.'
        ),
        **_QUANTITY,
    )
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
        default=None,
        description="Any supported instrument. Defaults to the configured default.",
    )


class OrderResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    symbol: str
    exchange: str
    asset_class: AssetClass
    side: OrderSide
    order_type: OrderType
    quantity: Quantity
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
    tds: Decimal = Field(
        default=Decimal("0.00"),
        description="Tax withheld on a crypto disposal. Always zero for a stock.",
    )
    total_charges: Decimal


class TradeResponse(BaseModel):
    """A fill priced end to end."""

    model_config = ConfigDict(from_attributes=True)

    id: int
    order_id: int
    symbol: str
    exchange: str
    asset_class: AssetClass
    side: OrderSide
    quantity: Quantity

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
    tds: Decimal = Field(
        default=Decimal("0.00"),
        description="Tax withheld on a crypto disposal. Always zero for a stock.",
    )
    total_charges: Decimal

    gross_pnl: Decimal = Field(
        description="P&L from price movement, before charges. Zero on an opening fill."
    )
    net_pnl: Decimal = Field(description="gross_pnl minus this fill's charges.")

    closed_quantity: Quantity
    created_at: datetime


class PositionResponse(BaseModel):
    """``quantity`` carries direction: >0 long, 0 flat, <0 short."""

    model_config = ConfigDict(from_attributes=True)

    symbol: str
    exchange: str
    asset_class: AssetClass
    quantity: Quantity
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
    quantity: Quantity
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
    asset_class: AssetClass = Field(
        description="Which charge schedule was applied."
    )
    quantity: Quantity
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


class PositionValuationResponse(BaseModel):
    """One instrument inside the multi-stock portfolio."""

    model_config = ConfigDict(from_attributes=True)

    symbol: str
    exchange: str
    asset_class: AssetClass
    quantity: Quantity = Field(description="Signed: >0 long, 0 flat, <0 short.")
    average_price: Decimal
    mark_price: Decimal | None = Field(
        default=None, description="Price it was valued at. Null when unpriced or flat."
    )
    position_value: Decimal
    unrealized_pnl: Decimal
    realized_pnl: Decimal
    total_charges: Decimal
    net_realized_pnl: Decimal


class PortfolioSummaryResponse(BaseModel):
    """The whole account: one wallet, many instruments.

    Every total is summed across all instruments ever traded. An open position
    with no supplied mark price contributes zero and is named in
    ``unpriced_symbols`` -- the engine never fetches prices itself.
    """

    model_config = ConfigDict(from_attributes=True)

    cash_balance: Decimal
    initial_balance: Decimal
    realized_pnl: Decimal = Field(description="Gross, before charges, across all stocks.")
    total_charges: Decimal
    net_realized_pnl: Decimal
    unrealized_pnl: Decimal
    position_value: Decimal
    total_equity: Decimal = Field(description="cash + total position value.")
    total_pnl: Decimal
    net_total_pnl: Decimal = Field(description="The figure after all costs.")
    currency: str
    positions: list[PositionValuationResponse]
    unpriced_symbols: list[str] = Field(
        description="Open positions no mark price was supplied for."
    )
    value_by_asset_class: dict[AssetClass, Decimal] = Field(
        default_factory=dict,
        description=(
            "Position value split by asset class. A breakdown of ONE cash pool, "
            "not separate balances -- the wallet funds every class."
        ),
    )
