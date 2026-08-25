"""Market-data endpoints -- transport only.

Read-only. Nothing here touches the wallet or places an order; that is a later
stage.
"""

from datetime import datetime
from typing import Annotated

from fastapi import APIRouter, Depends, Query

from app.market_data.base import MarketDataProvider
from app.market_data.registry import get_provider
from app.schemas.market_data import (
    CandleSeries,
    Interval,
    ProviderCapabilities,
    Quote,
)
from app.services.market_data_service import RelianceMarketDataService

router = APIRouter(prefix="/market-data", tags=["market-data"])


def get_market_data_service(
    provider: Annotated[MarketDataProvider, Depends(get_provider)],
) -> RelianceMarketDataService:
    """Build the service around the configured provider.

    Declared as a dependency so tests can override the provider with a fake and
    never touch the network.
    """
    return RelianceMarketDataService(provider)


ServiceDep = Annotated[RelianceMarketDataService, Depends(get_market_data_service)]


@router.get(
    "/provider",
    response_model=ProviderCapabilities,
    summary="What the configured market-data feed supports",
)
async def get_provider_capabilities(service: ServiceDep) -> ProviderCapabilities:
    """Report the feed's real capabilities and limitations.

    Check this before relying on ``bid``/``ask`` or on live streaming -- not
    every provider supplies them.
    """
    return service.capabilities


@router.get(
    "/quote",
    response_model=Quote,
    summary="Current RELIANCE quote",
    responses={
        400: {"description": "Symbol other than RELIANCE requested."},
        503: {"description": "Upstream market-data provider is unavailable."},
    },
)
async def get_quote(
    service: ServiceDep,
    symbol: Annotated[
        str | None,
        Query(description="Optional. Must be RELIANCE if supplied."),
    ] = None,
) -> Quote:
    """Latest traded price for NSE:RELIANCE.

    ``bid`` and ``ask`` are ``null`` when the configured provider carries no
    order-book depth -- see ``GET /market-data/provider``.
    """
    return await service.get_current_quote(symbol)


@router.get(
    "/candles",
    response_model=CandleSeries,
    summary="Historical RELIANCE OHLCV candles",
    responses={
        400: {"description": "Unsupported symbol or interval."},
        503: {"description": "Upstream market-data provider is unavailable."},
    },
)
async def get_candles(
    service: ServiceDep,
    interval: Annotated[
        Interval, Query(description="Candle size.")
    ] = Interval.ONE_DAY,
    start: Annotated[
        datetime | None,
        Query(description="Window start (ISO 8601). Omit for the provider default."),
    ] = None,
    end: Annotated[
        datetime | None, Query(description="Window end (ISO 8601). Defaults to now.")
    ] = None,
    limit: Annotated[
        int | None,
        Query(ge=1, le=5000, description="Keep only the most recent N candles."),
    ] = None,
    symbol: Annotated[
        str | None, Query(description="Optional. Must be RELIANCE if supplied.")
    ] = None,
) -> CandleSeries:
    """OHLCV history, oldest candle first.

    Omitting ``start`` returns the provider's default lookback for the
    interval. Bars the exchange never printed are omitted rather than
    forward-filled.
    """
    return await service.get_historical_candles(
        interval=interval, start=start, end=end, limit=limit, symbol=symbol
    )
