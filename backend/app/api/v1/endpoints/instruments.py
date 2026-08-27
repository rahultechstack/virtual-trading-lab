"""Instrument endpoints -- transport only.

The backend is the source of truth for which stocks may be traded. The
frontend renders whatever this returns and never maintains its own list.
"""

from typing import Annotated

from fastapi import APIRouter, Depends, Query

from app.market_data.base import MarketDataProvider
from app.market_data.instruments import instrument_registry, resolve_instrument
from app.market_data.registry import get_provider
from app.schemas.instruments import InstrumentResponse

router = APIRouter(prefix="/instruments", tags=["instruments"])

ProviderDep = Annotated[MarketDataProvider, Depends(get_provider)]


def _to_response(instrument, *, data_available: bool | None) -> InstrumentResponse:
    return InstrumentResponse(
        symbol=instrument.symbol,
        company_name=instrument.company_name,
        exchange=instrument.exchange,
        instrument_type=instrument.instrument_type,
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
        Query(description="Match on trading symbol or company name."),
    ] = None,
    limit: Annotated[int, Query(ge=1, le=500)] = 50,
) -> list[InstrumentResponse]:
    """The tradable universe.

    Every entry is an instrument the configured provider is known to serve --
    the catalogue is curated for that reason rather than mirroring the full
    exchange listing. ``data_available`` reflects any probe already performed;
    call ``/instruments/{symbol}`` to force one.

    Search matches symbol before company name, and a prefix before a substring,
    so "TCS" returns Tata Consultancy first.
    """
    matches = instrument_registry.search(search, limit=limit)
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
async def get_instrument(symbol: str, provider: ProviderDep) -> InstrumentResponse:
    """Resolve one instrument and confirm the provider can serve it.

    The availability probe is cached per process, so selecting the same stock
    repeatedly costs one upstream call in total.
    """
    instrument = resolve_instrument(symbol)
    available = await instrument_registry.verify(instrument.symbol, provider)
    return _to_response(instrument, data_available=available)
