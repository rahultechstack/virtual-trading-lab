"""Market calendar endpoints -- transport only.

The calendar layer decides whether a market is open; this exposes that answer
so the frontend can render it without reimplementing any schedule. No trading
schedule logic lives here.
"""

from datetime import UTC, datetime
from typing import Annotated

from fastapi import APIRouter, Query

from app.core.config import settings
from app.market_data.instruments import AssetClass, resolve_instrument
from app.markets.registry import calendar_for
from app.schemas.markets import MarketStatusResponse

router = APIRouter(prefix="/markets", tags=["markets"])


def _status_for(symbol: str | None) -> MarketStatusResponse:
    instrument = resolve_instrument(symbol)
    calendar = calendar_for(instrument)
    session = calendar.trading_status()

    return MarketStatusResponse(
        symbol=instrument.symbol,
        asset_class=instrument.asset_class,
        market=instrument.market,
        calendar=calendar.name,
        status=session.status,
        is_open=session.is_open,
        is_24x7=calendar.is_continuous,
        timezone=session.timezone,
        server_time=session.at,
        next_open=session.next_open,
        next_close=session.next_close,
        reason=session.reason,
        enforced=settings.ENFORCE_MARKET_HOURS,
    )


@router.get(
    "/status",
    response_model=MarketStatusResponse,
    summary="Whether an instrument's market is open right now",
    responses={400: {"description": "Symbol is not in the supported universe."}},
)
async def market_status(
    symbol: Annotated[
        str | None,
        Query(description="Defaults to the configured default instrument."),
    ] = None,
) -> MarketStatusResponse:
    """Trading status for one instrument.

    A crypto symbol always reports ``OPEN`` with null ``next_open`` and
    ``next_close`` -- a continuous market has no boundaries, and reporting the
    next open as "now" would invent one.

    ``enforced`` says whether being closed actually blocks an order. With it
    false the status is informational and the engine still accepts orders,
    which is the default for a paper-trading lab.
    """
    return _status_for(symbol)


@router.get(
    "/statuses",
    response_model=list[MarketStatusResponse],
    summary="Trading status of every asset class at once",
)
async def market_statuses() -> list[MarketStatusResponse]:
    """One row per asset class, using each class's first catalogue instrument.

    Lets a client show "NSE closed, crypto open" without a request per symbol.
    """
    from app.market_data.instruments import instrument_registry

    rows: list[MarketStatusResponse] = []
    for asset_class in AssetClass:
        instruments = instrument_registry.all(asset_class)
        if instruments:
            rows.append(_status_for(instruments[0].symbol))
    return rows


@router.get(
    "/clock",
    summary="Server time, for a client that wants to align its own clock",
)
async def server_clock() -> dict:
    """UTC now, plus the NSE session's local time.

    Exists because the frontend renders exchange-local timestamps and should
    not infer the offset from the browser's own timezone.
    """
    from zoneinfo import ZoneInfo

    now = datetime.now(tz=UTC)
    return {
        "utc": now.isoformat(),
        "exchange_timezone": settings.NSE_TIMEZONE,
        "exchange_time": now.astimezone(ZoneInfo(settings.NSE_TIMEZONE)).isoformat(),
    }
