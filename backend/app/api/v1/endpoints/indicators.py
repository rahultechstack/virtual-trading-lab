"""Indicator endpoints -- transport only.

Indicators are computed from the same candles the chart draws, fetched through
the market-data service, so what the study sees is exactly what is on screen.
"""

from datetime import datetime
from typing import Annotated

from fastapi import APIRouter, Depends, Query

from app.api.v1.endpoints.market_data import get_market_data_service
from app.indicators.definitions import parse_specs
from app.indicators.service import indicator_service
from app.schemas.indicators import (
    IndicatorCatalogueEntry,
    IndicatorResponse,
    IndicatorSetResponse,
)
from app.schemas.market_data import Interval
from app.services.market_data_service import RelianceMarketDataService

router = APIRouter(prefix="/indicators", tags=["indicators"])

ServiceDep = Annotated[RelianceMarketDataService, Depends(get_market_data_service)]


@router.get(
    "/catalogue",
    response_model=list[IndicatorCatalogueEntry],
    summary="Available indicators and their parameters",
)
async def catalogue() -> list[IndicatorCatalogueEntry]:
    """What can be requested, with defaults and bounds."""
    return [
        IndicatorCatalogueEntry.model_validate(entry)
        for entry in indicator_service.catalogue()
    ]


@router.get(
    "",
    response_model=IndicatorSetResponse,
    summary="Compute indicators over RELIANCE candles",
    responses={
        400: {"description": "Unknown indicator, bad parameters, or bad interval."},
        503: {"description": "Upstream market-data provider is unavailable."},
    },
)
async def compute_indicators(
    service: ServiceDep,
    indicators: Annotated[
        str,
        Query(
            description=(
                "Comma-separated specs: sma:20,ema:21,rsi:14,macd:12:26:9,"
                "bbands:20:2,vwap. Omitted parameters use their defaults."
            )
        ),
    ],
    interval: Annotated[Interval, Query(description="Candle size.")] = Interval.ONE_DAY,
    limit: Annotated[
        int, Query(ge=2, le=5000, description="How many candles to compute over.")
    ] = 250,
    start: Annotated[datetime | None, Query(description="Window start.")] = None,
    end: Annotated[datetime | None, Query(description="Window end.")] = None,
) -> IndicatorSetResponse:
    """Compute the requested studies from real candle data.

    Warm-up bars are omitted rather than sent as nulls -- a moving average
    that does not exist yet should not be drawn. ``warmup`` reports how many
    were skipped, and ``insufficient_data`` flags a window too short to
    produce anything.
    """
    specs = parse_specs(indicators)

    series = await service.get_historical_candles(
        interval=interval, start=start, end=end, limit=limit
    )

    results = indicator_service.calculate(
        candles=series.candles, specs=specs, interval=interval.value
    )

    return IndicatorSetResponse(
        symbol=series.symbol,
        exchange=series.exchange,
        interval=series.interval,
        provider=series.provider,
        candle_count=series.count,
        indicators=[IndicatorResponse.model_validate(result) for result in results],
    )
