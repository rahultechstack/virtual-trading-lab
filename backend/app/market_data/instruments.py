"""Instrument lookup, search and validation.

    catalogue.py        WHAT is tradable  (the data -- edit that file to add one)
    instrument_types.py the vocabulary    (AssetClass, Instrument, steps)
    instruments.py      THIS FILE         (registry, resolution, quantity rules)

This module is the single place the backend decides whether a symbol may be
traded, so the trading engine, the market-data service and the automation
service can never disagree about the universe.

An instrument is tradable only when it is **both** in the catalogue **and**
served by the provider configured for its asset class -- ``data_available`` is
verified against that provider rather than assumed, and cached so the check
costs one upstream call per symbol per process.

Everything the rest of the codebase imported from here still lives here: the
types and the catalogue are re-exported below, so ``from
app.market_data.instruments import AssetClass`` keeps working.
"""

from decimal import Decimal

from app.core.logging import get_logger
from app.market_data.catalogue import (
    ALL_INSTRUMENTS,
    CRYPTO_INSTRUMENTS,
    NSE_INSTRUMENTS,
)
from app.market_data.instrument_types import (
    SATOSHI,
    WHOLE_UNITS,
    AssetClass,
    Instrument,
    InstrumentType,
)

logger = get_logger(__name__)

__all__ = [
    # Re-exported so existing imports keep working. The definitions live in
    # instrument_types.py and catalogue.py.
    "ALL_INSTRUMENTS",
    "CRYPTO_INSTRUMENTS",
    "NSE_INSTRUMENTS",
    "SATOSHI",
    "WHOLE_UNITS",
    "AssetClass",
    "Instrument",
    "InstrumentType",
    # Defined here.
    "InstrumentRegistry",
    "asset_class_for",
    "instrument_registry",
    "normalise_quantity",
    "resolve_instrument",
    "resolve_symbol",
]


class InstrumentRegistry:
    """Lookup, search and availability for the supported universe."""

    def __init__(self, instruments: tuple[Instrument, ...] = ALL_INSTRUMENTS) -> None:
        self._by_symbol: dict[str, Instrument] = {
            instrument.symbol.upper(): instrument for instrument in instruments
        }
        self._instruments = instruments
        #: symbol -> whether the provider served it. Populated on demand.
        self._availability: dict[str, bool] = {}

    # -- catalogue -------------------------------------------------------

    def all(self, asset_class: AssetClass | None = None) -> list[Instrument]:
        if asset_class is None:
            return list(self._instruments)
        return [
            instrument
            for instrument in self._instruments
            if instrument.asset_class is asset_class
        ]

    def get(self, symbol: str | None) -> Instrument | None:
        if symbol is None:
            return None
        return self._by_symbol.get(symbol.strip().upper())

    def is_known(self, symbol: str | None) -> bool:
        return self.get(symbol) is not None

    def search(
        self,
        query: str | None = None,
        *,
        asset_class: AssetClass | None = None,
        limit: int = 50,
    ) -> list[Instrument]:
        """Match on symbol or asset/company name, case-insensitively.

        Symbol matches rank above name matches, and a prefix match above a
        substring one, so "TCS" puts Tata Consultancy first rather than any
        company whose name happens to contain it -- and "bitcoin" finds BTC by
        name alone.

        ``asset_class`` narrows the universe first, which is what backs the
        All / Stocks / Crypto filter in the UI.
        """
        candidates = self.all(asset_class)

        if not query or not query.strip():
            return candidates[:limit]

        needle = query.strip().lower()
        scored: list[tuple[int, Instrument]] = []

        for instrument in candidates:
            symbol = instrument.symbol.lower()
            name = instrument.company_name.lower()

            if symbol == needle:
                score = 0
            elif symbol.startswith(needle):
                score = 1
            elif name.startswith(needle):
                score = 2
            elif needle in symbol:
                score = 3
            elif needle in name:
                score = 4
            else:
                continue
            scored.append((score, instrument))

        scored.sort(key=lambda entry: (entry[0], entry[1].symbol))
        return [instrument for _, instrument in scored[:limit]]

    # -- availability ----------------------------------------------------

    def cached_availability(self, symbol: str) -> bool | None:
        """What we already know about this symbol, without calling upstream."""
        return self._availability.get(symbol.strip().upper())

    def remember_availability(self, symbol: str, available: bool) -> None:
        self._availability[symbol.strip().upper()] = available

    async def verify(self, symbol: str, provider=None) -> bool:
        """Ask the provider whether it can actually serve this symbol.

        ``provider`` defaults to the one routed for the instrument's asset
        class, so a crypto symbol is never probed against the equity feed.
        Cached per process: a symbol is probed at most once, because the answer
        is a property of the feed rather than of the moment.
        """
        instrument = self.get(symbol)
        if instrument is None:
            return False

        cached = self.cached_availability(instrument.symbol)
        if cached is not None:
            return cached

        if provider is None:
            from app.market_data.router import provider_for

            provider = provider_for(instrument)

        try:
            await provider.get_current_quote(instrument.symbol, instrument.exchange)
            available = True
        except Exception as exc:  # noqa: BLE001 - any failure means "cannot serve"
            logger.info(
                "Instrument %s is not available from the provider: %s",
                instrument.symbol,
                exc,
            )
            available = False

        self.remember_availability(instrument.symbol, available)
        return available

    def reset_availability(self) -> None:
        """Forget cached probes. Used by tests."""
        self._availability.clear()


#: Process-wide registry. The catalogue is static, so one instance is enough.
instrument_registry = InstrumentRegistry()


def resolve_instrument(symbol: str | None) -> Instrument:
    """Resolve a requested symbol to a supported :class:`Instrument`.

    ``None`` falls back to ``settings.TRADING_SYMBOL``, which is the *default*
    instrument the platform opens on -- not a restriction. This is the single
    place the whole backend decides whether a symbol may be traded, so the
    trading engine, the market-data service and the automation service can
    never disagree about the universe.

    Raises:
        UnsupportedSymbolError: the symbol is not in the supported universe.
    """
    from app.core.config import settings
    from app.core.exceptions import UnsupportedSymbolError

    requested = symbol if symbol is not None else settings.TRADING_SYMBOL
    instrument = instrument_registry.get(requested)
    if instrument is None:
        raise UnsupportedSymbolError(
            f"'{requested}' is not a supported instrument. "
            f"Call GET /api/v1/instruments for the tradable universe."
        )
    return instrument


def resolve_symbol(symbol: str | None) -> str:
    """The canonical, upper-cased symbol for a request. See ``resolve_instrument``."""
    return resolve_instrument(symbol).symbol


def asset_class_for(symbol: str | None) -> AssetClass:
    """The asset class a symbol belongs to. Rejects unsupported symbols."""
    return resolve_instrument(symbol).asset_class


def normalise_quantity(instrument: Instrument, quantity) -> Decimal:
    """Validate a requested size against the instrument's tradable increment.

    This is the one place the platform decides what a legal size is, and the
    rule comes from the instrument rather than from any assumption that
    quantities are whole numbers:

    * a stock has ``quantity_step`` 1, so ``0.5`` shares is refused;
    * crypto has ``quantity_step`` 0.00000001, so ``0.001`` BTC is accepted
      but a size finer than one satoshi is refused.

    Returned exact, never rounded -- silently snapping 0.15 shares to 0 (or to
    1) would trade a size the caller did not ask for.

    Raises:
        InvalidQuantityError: not a number, not positive, or off-step.
    """
    from app.core.exceptions import InvalidQuantityError

    try:
        value = Decimal(str(quantity))
    except (ArithmeticError, ValueError, TypeError):
        raise InvalidQuantityError(f"Quantity '{quantity}' is not a number.") from None

    if not value.is_finite():
        raise InvalidQuantityError(f"Quantity '{quantity}' is not a finite number.")
    if value <= 0:
        raise InvalidQuantityError(f"Quantity must be positive, got {value}.")

    step = instrument.quantity_step
    if value % step != 0:
        if not instrument.is_fractional:
            raise InvalidQuantityError(
                f"{instrument.symbol} trades in whole units; {value} is not a "
                f"whole number of shares."
            )
        raise InvalidQuantityError(
            f"{instrument.symbol} trades in increments of {step:f}; "
            f"{value} is not a multiple of it."
        )

    return value
