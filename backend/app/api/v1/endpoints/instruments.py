"""Instrument endpoints -- transport only.

The backend is the source of truth for which instruments may be traded, across
every asset class. The frontend renders whatever this returns and never
maintains its own list of stocks or coins.
"""

from typing import Annotated

from fastapi import APIRouter, Query

from app.core.config import settings
from app.market_data.instruments import (
    AssetClass,
    instrument_registry,
    resolve_instrument,
)
from app.schemas.instruments import InstrumentResponse

router = APIRouter(prefix="/instruments", tags=["instruments"])


def _to_response(instrument, *, data_available: bool | None) -> InstrumentResponse:
    return InstrumentResponse(
        symbol=instrument.symbol,
        company_name=instrument.company_name,
        asset_class=instrument.asset_class,
        exchange=instrument.exchange,
        market=instrument.market,
        trading_hours=instrument.trading_hours,
        instrument_type=instrument.instrument_type,
        quantity_step=instrument.quantity_step,
        data_available=data_available,
    )


@router.get(
    "",
    response_model=list[InstrumentResponse],
    summary="Supported instruments, with optional search",
)
async def list_instruments(
    search: Annotated[
        str | None,
        Query(description="Match on trading symbol or company/asset name."),
    ] = None,
    asset_class: Annotated[
        AssetClass | None,
        Query(description="Restrict to STOCK or CRYPTO. Omit for everything."),
    ] = None,
    limit: Annotated[int, Query(ge=1, le=settings.MAX_HISTORY_PAGE_SIZE)] = 50,
) -> list[InstrumentResponse]:
    """The tradable universe, across every asset class.

    Every entry is an instrument the provider routed for its asset class is
    known to serve -- the catalogue is curated for that reason rather than
    mirroring a full exchange listing. ``data_available`` reflects any probe
    already performed; call ``/instruments/{symbol}`` to force one.

    Search matches symbol before name, and a prefix before a substring, so
    "TCS" returns Tata Consultancy first and "bitcoin" finds BTC by name.
    ``asset_class`` narrows first, which backs the All / Stocks / Crypto filter.
    """
    matches = instrument_registry.search(
        search, asset_class=asset_class, limit=limit
    )
    return [
        _to_response(
            instrument,
            data_available=instrument_registry.cached_availability(instrument.symbol),
        )
        for instrument in matches
    ]


@router.get(
    "/{symbol}",
    response_model=InstrumentResponse,
    summary="One instrument, with its data availability verified",
    responses={400: {"description": "Symbol is not in the supported universe."}},
)
async def get_instrument(symbol: str) -> InstrumentResponse:
    """Resolve one instrument and confirm its provider can serve it.

    The probe goes to the feed routed for this instrument's asset class, so a
    coin is verified against the crypto feed rather than the equity one. It is
    cached per process, so selecting the same instrument repeatedly costs one
    upstream call in total.
    """
    instrument = resolve_instrument(symbol)
    available = await instrument_registry.verify(instrument.symbol)
    return _to_response(instrument, data_available=available)
