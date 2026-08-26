"""Strategy and backtest endpoints -- transport only.

The strategy engine and backtester are usable without any of this; these
functions just expose them over HTTP.
"""

from typing import Annotated

from fastapi import APIRouter, Depends

from app.backtest.engine import BacktestConfig, BacktestEngine
from app.api.v1.endpoints.market_data import get_market_data_service
from app.schemas.backtest import (
    BacktestRequest,
    BacktestResultSchema,
    StrategySchema,
)
from app.services.market_data_service import RelianceMarketDataService
from app.strategies.registry import create_strategy, describe_all

router = APIRouter(prefix="/strategies", tags=["strategies"])

ServiceDep = Annotated[RelianceMarketDataService, Depends(get_market_data_service)]


@router.get("", response_model=list[StrategySchema], summary="Available strategies")
async def list_strategies() -> list[StrategySchema]:
    """Every registered strategy with its parameters and defaults."""
    return [StrategySchema.model_validate(entry) for entry in describe_all()]


@router.post(
    "/backtest",
    response_model=BacktestResultSchema,
    summary="Run a backtest over historical candles for the configured instrument",
    responses={
        400: {"description": "Unknown strategy or invalid parameters."},
        503: {"description": "Upstream market-data provider is unavailable."},
    },
)
async def run_backtest(
    service: ServiceDep, payload: BacktestRequest
) -> BacktestResultSchema:
    """Run a strategy over history and report what it would have done.

    Fills are priced through the live execution models -- spread, slippage and
    the full Indian charge schedule -- and accounted for with the same
    position logic, so the numbers are comparable to real trading.

    By default a signal fills against the **next** bar's open, because the
    close that produced it was not tradable at the moment of the decision.
    """
    strategy = create_strategy(payload.strategy, payload.params)

    series = await service.get_historical_candles(
        interval=payload.interval,
        start=payload.start,
        end=payload.end,
        limit=payload.limit,
    )

    engine = BacktestEngine(
        config=BacktestConfig(
            initial_capital=payload.initial_capital,
            fill_timing=payload.fill_timing,
            sizing_mode=payload.sizing_mode,
            equity_percent=payload.equity_percent,
            fixed_quantity=payload.fixed_quantity,
            fixed_value=payload.fixed_value,
            close_at_end=payload.close_at_end,
        )
    )

    result = engine.run(
        strategy=strategy,
        candles=series.candles,
        symbol=series.symbol,
        exchange=series.exchange,
        interval=series.interval.value,
    )
    return BacktestResultSchema.model_validate(result)
