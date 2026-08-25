"""Trading endpoints -- transport only.

The engine holds every rule; these functions translate HTTP to engine calls
and back. The engine is usable without them.
"""

from decimal import Decimal
from types import SimpleNamespace
from typing import Annotated

from fastapi import APIRouter, Query, status

from app.api.deps import DbSession
from app.models.enums import OrderSide, OrderStatus
from app.schemas.trading import (
    ChargesResponse,
    ExecutionCostPreview,
    OrderResponse,
    OrderResultResponse,
    PlaceOrderRequest,
    PortfolioResponse,
    PositionResponse,
    TradeResponse,
)
from app.trading.engine import TradingEngine
from app.trading.execution import ExecutionEngine

router = APIRouter(prefix="/trading", tags=["trading"])


@router.post(
    "/orders",
    response_model=OrderResultResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Place an order",
    responses={
        400: {"description": "Invalid order, bad position operation, or no funds."},
        404: {"description": "Wallet has not been initialised."},
    },
)
async def place_order(
    session: DbSession, payload: PlaceOrderRequest
) -> OrderResultResponse:
    """Execute an order atomically against the virtual account.

    The fill price is derived from ``reference_price`` by the spread and
    slippage models, then charges are applied. Order, trade, position and
    wallet all move together or not at all.
    """
    result = await TradingEngine(session).place_order(
        side=payload.side,
        quantity=payload.quantity,
        reference_price=payload.reference_price,
        symbol=payload.symbol,
        requested_price=payload.requested_price,
    )
    return OrderResultResponse(
        order=OrderResponse.model_validate(result.order),
        trade=TradeResponse.model_validate(result.trade),
        position=PositionResponse.model_validate(result.position),
        gross_pnl=result.gross_pnl,
        total_charges=result.total_charges,
        net_pnl=result.net_pnl,
        cash_delta=result.cash_delta,
    )


@router.get("/orders", response_model=list[OrderResponse], summary="Order history")
async def list_orders(
    session: DbSession,
    limit: Annotated[int, Query(ge=1, le=500)] = 100,
    offset: Annotated[int, Query(ge=0)] = 0,
    order_status: Annotated[
        OrderStatus | None, Query(alias="status", description="Filter by status.")
    ] = None,
) -> list[OrderResponse]:
    """Newest first. Includes rejected orders."""
    orders = await TradingEngine(session).list_orders(
        limit=limit, offset=offset, status=order_status
    )
    return [OrderResponse.model_validate(order) for order in orders]


@router.get("/trades", response_model=list[TradeResponse], summary="Trade history")
async def list_trades(
    session: DbSession,
    limit: Annotated[int, Query(ge=1, le=500)] = 100,
    offset: Annotated[int, Query(ge=0)] = 0,
) -> list[TradeResponse]:
    """Newest first."""
    trades = await TradingEngine(session).list_trades(limit=limit, offset=offset)
    return [TradeResponse.model_validate(trade) for trade in trades]


@router.get(
    "/position", response_model=PositionResponse, summary="Current RELIANCE position"
)
async def get_position(session: DbSession) -> PositionResponse:
    """``quantity`` carries direction: >0 long, 0 flat, <0 short."""
    position = await TradingEngine(session).get_position()
    return PositionResponse.model_validate(position)


@router.get(
    "/portfolio",
    response_model=PortfolioResponse,
    summary="Account valuation",
    responses={404: {"description": "Wallet has not been initialised."}},
)
async def get_portfolio(
    session: DbSession,
    mark_price: Annotated[
        Decimal | None,
        Query(gt=0, description="Price to value the open position at."),
    ] = None,
) -> PortfolioResponse:
    """Cash, position and P&L.

    Supply ``mark_price`` to value the open position -- the engine does not
    fetch prices itself, which is what keeps it independent of the market-data
    layer. Without it, unrealized P&L and position value report zero.
    """
    snapshot = await TradingEngine(session).get_portfolio(mark_price=mark_price)
    return PortfolioResponse(**vars(snapshot))


@router.get(
    "/execution-cost",
    response_model=ExecutionCostPreview,
    summary="Preview spread, slippage and charges without trading",
)
async def preview_execution_cost(
    session: DbSession,
    side: Annotated[OrderSide, Query(description="Side to price.")],
    quantity: Annotated[int, Query(ge=1, le=10_000_000)],
    reference_price: Annotated[Decimal, Query(gt=0, description="Mid price.")],
) -> ExecutionCostPreview:
    """Price a hypothetical order.

    Runs the same spread, slippage and fee models the engine uses, but writes
    nothing -- useful for seeing what an order would actually cost.
    """
    engine = ExecutionEngine(session)
    order = SimpleNamespace(side=side, quantity=quantity)
    fill = engine.execute(order, reference_price)

    return ExecutionCostPreview(
        side=side,
        quantity=quantity,
        reference_price=reference_price,
        bid_price=fill.quote.bid,
        ask_price=fill.quote.ask,
        spread=fill.quote.spread,
        execution_price=fill.price,
        spread_cost=fill.spread_cost,
        slippage_cost=fill.slippage_cost,
        charges=ChargesResponse(
            brokerage=fill.charges.brokerage,
            stt=fill.charges.stt,
            exchange_charges=fill.charges.exchange_charges,
            sebi_charges=fill.charges.sebi_charges,
            stamp_duty=fill.charges.stamp_duty,
            gst=fill.charges.gst,
            dp_charges=fill.charges.dp_charges,
            total_charges=fill.charges.total,
        ),
        total_execution_cost=fill.execution_cost,
    )
