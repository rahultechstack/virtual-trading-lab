"""Market-data endpoints -- transport only.

Read-only. Nothing here touches the wallet or places an order; that is a later
stage.
"""

from datetime import datetime
from typing import Annotated

from fastapi import APIRouter, Depends, Query

from app.core.config import settings
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
    """Build the service for this request.

    Normally the service is built with **no** provider, so each instrument is
    served by the feed routed for its asset class -- otherwise asking for BTC
    would reach the equity feed, which resolves the bare ticker "BTC" to an
    unrelated US-listed security and returns a price in dollars.

    ``get_provider`` is still declared as a dependency because overriding it is
    how tests substitute a fake feed. When it has been overridden, that
    provider is honoured for every asset class; when it has not, routing wins.
    """
    from app.market_data.registry import is_default_provider

    routed = None if is_default_provider(provider) else provider
    return RelianceMarketDataService(routed)


ServiceDep = Annotated[RelianceMarketDataService, Depends(get_market_data_service)]


@router.get(
    "/provider",
    response_model=ProviderCapabilities,
    summary="What the configured market-data feed supports",
)
async def get_provider_capabilities(
    service: ServiceDep,
    symbol: Annotated[
        str | None,
        Query(
            description=(
                "Report the feed serving this instrument. Capabilities differ "
                "per asset class. Defaults to the default instrument."
            )
        ),
    ] = None,
) -> ProviderCapabilities:
    """Report the feed's real capabilities and limitations.

    Check this before relying on ``bid``/``ask`` or on live streaming -- not
    every provider supplies them, and the crypto feed and the equity feed do
    not necessarily agree.
    """
    return service.capabilities_for(symbol)


@router.get(
    "/quote",
    response_model=Quote,
    summary="Current quote for the configured instrument",
    responses={
        400: {"description": "A symbol other than the configured one was requested."},
        503: {"description": "Upstream market-data provider is unavailable."},
    },
)
async def get_quote(
    service: ServiceDep,
    symbol: Annotated[
        str | None,
        Query(description="Optional. Must be the configured symbol if supplied."),
    ] = None,
) -> Quote:
    """Latest traded price for the configured instrument (see TRADING_SYMBOL).

    ``bid`` and ``ask`` are ``null`` when the configured provider carries no
    order-book depth -- see ``GET /market-data/provider``.
    """
    return await service.get_current_quote(symbol)


@router.get(
    "/candles",
    response_model=CandleSeries,
    summary="Historical OHLCV candles for the configured instrument",
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
        Query(
            ge=1,
            le=settings.MAX_CANDLES_PER_REQUEST,
            description="Keep only the most recent N candles.",
        ),
    ] = None,
    symbol: Annotated[
        str | None, Query(description="Optional. Must be the configured symbol if supplied.")
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
