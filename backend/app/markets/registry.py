"""Calendar selection by asset class.

    AssetClass.STOCK  -> NSEMarketCalendar
    AssetClass.CRYPTO -> CryptoMarketCalendar

One table, one lookup. Callers ask for an *instrument* and get the calendar
that governs it; nothing outside this module maps an asset class to a
schedule, so adding ETF or INDEX later is one entry here.

Calendars are cached per asset class because they are immutable and reading
the holiday list on every price tick would be wasteful. ``reset_calendars()``
clears the cache when settings change -- which in practice means tests.
"""

from app.core.logging import get_logger
from app.markets.calendar import (
    CryptoMarketCalendar,
    MarketCalendar,
    MarketSession,
    NSEMarketCalendar,
)
from app.market_data.instruments import AssetClass, Instrument, resolve_instrument

logger = get_logger(__name__)


def _build_stock_calendar() -> MarketCalendar:
    return NSEMarketCalendar.from_settings()


def _build_crypto_calendar() -> MarketCalendar:
    return CryptoMarketCalendar()


#: Asset class -> how to build its calendar.
_BUILDERS = {
    AssetClass.STOCK: _build_stock_calendar,
    AssetClass.CRYPTO: _build_crypto_calendar,
}

_cache: dict[AssetClass, MarketCalendar] = {}


def calendar_for_asset_class(asset_class: AssetClass) -> MarketCalendar:
    """The calendar governing an asset class, built once and cached."""
    calendar = _cache.get(asset_class)
    if calendar is None:
        builder = _BUILDERS.get(asset_class)
        if builder is None:  # pragma: no cover - unreachable while the enum is closed
            raise ValueError(f"No market calendar registered for {asset_class}.")
        calendar = builder()
        _cache[asset_class] = calendar
    return calendar


def calendar_for(instrument: Instrument) -> MarketCalendar:
    """The calendar governing one instrument."""
    return calendar_for_asset_class(instrument.asset_class)


def calendar_for_symbol(symbol: str | None) -> MarketCalendar:
    """The calendar for a symbol. Rejects symbols outside the universe."""
    return calendar_for(resolve_instrument(symbol))


def trading_status_for(symbol: str | None, at=None) -> MarketSession:
    """What the market for ``symbol`` is doing. The one call the API needs."""
    return calendar_for_symbol(symbol).trading_status(at)


def is_tradable_now(symbol: str | None, at=None) -> bool:
    """Whether ``symbol`` may be traded at ``at``. Crypto is always True."""
    return calendar_for_symbol(symbol).is_market_open(at)


def reset_calendars() -> None:
    """Drop cached calendars so changed settings take effect. Used by tests."""
    _cache.clear()
