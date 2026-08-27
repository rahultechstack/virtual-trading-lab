"""The tradable instrument universe.

The backend is the source of truth for which stocks this platform supports.
An instrument is tradable only when it is **both** in the catalogue below and
served by the configured market-data provider -- ``data_available`` is verified
against the provider rather than assumed, and cached so the check costs one
upstream call per symbol per process.

Why a curated catalogue rather than the full NSE master list: the configured
provider (Yahoo) has no instrument-discovery endpoint, so there is nothing to
enumerate from. Listing all ~2,000 NSE symbols would advertise instruments the
feed cannot actually serve, which the brief explicitly rules out. The catalogue
holds liquid, large-cap NSE names that Yahoo does serve.

To support another exchange later, add its instruments here with the right
``exchange`` code and add the vendor suffix to
``app.market_data.yahoo._EXCHANGE_SUFFIX``.
"""

from dataclasses import dataclass
from enum import StrEnum

from app.core.logging import get_logger

logger = get_logger(__name__)


class InstrumentType(StrEnum):
    """What kind of instrument this is. Only equities are supported today."""

    EQUITY = "EQUITY"


@dataclass(frozen=True)
class Instrument:
    """One tradable instrument.

    ``data_available`` is not stored on the catalogue entry -- it is resolved
    per request by :class:`InstrumentRegistry`, because availability is a
    property of the *provider*, not of the listing.
    """

    symbol: str
    company_name: str
    exchange: str = "NSE"
    instrument_type: InstrumentType = InstrumentType.EQUITY

    @property
    def display_name(self) -> str:
        return f"{self.exchange}:{self.symbol}"


def _nse(symbol: str, company_name: str) -> Instrument:
    return Instrument(symbol=symbol, company_name=company_name, exchange="NSE")


#: Curated NSE equities the configured provider serves. Ordered by how likely
#: they are to be wanted, not alphabetically, so the default dropdown is useful.
NSE_INSTRUMENTS: tuple[Instrument, ...] = (
    _nse("RELIANCE", "Reliance Industries"),
    _nse("TCS", "Tata Consultancy Services"),
    _nse("HDFCBANK", "HDFC Bank"),
    _nse("INFY", "Infosys"),
    _nse("ICICIBANK", "ICICI Bank"),
    _nse("HINDUNILVR", "Hindustan Unilever"),
    _nse("SBIN", "State Bank of India"),
    _nse("BHARTIARTL", "Bharti Airtel"),
    _nse("ITC", "ITC"),
    _nse("LT", "Larsen & Toubro"),
    _nse("KOTAKBANK", "Kotak Mahindra Bank"),
    _nse("AXISBANK", "Axis Bank"),
    _nse("BAJFINANCE", "Bajaj Finance"),
    _nse("ASIANPAINT", "Asian Paints"),
    _nse("MARUTI", "Maruti Suzuki India"),
    _nse("HCLTECH", "HCL Technologies"),
    _nse("SUNPHARMA", "Sun Pharmaceutical Industries"),
    _nse("TITAN", "Titan Company"),
    _nse("ULTRACEMCO", "UltraTech Cement"),
    _nse("WIPRO", "Wipro"),
    _nse("NESTLEIND", "Nestle India"),
    _nse("ONGC", "Oil & Natural Gas Corporation"),
    _nse("NTPC", "NTPC"),
    _nse("POWERGRID", "Power Grid Corporation of India"),
    _nse("TATAMOTORS", "Tata Motors"),
    _nse("TATASTEEL", "Tata Steel"),
    _nse("JSWSTEEL", "JSW Steel"),
    _nse("ADANIENT", "Adani Enterprises"),
    _nse("ADANIPORTS", "Adani Ports and SEZ"),
    _nse("COALINDIA", "Coal India"),
    _nse("GRASIM", "Grasim Industries"),
    _nse("HINDALCO", "Hindalco Industries"),
    _nse("CIPLA", "Cipla"),
    _nse("DRREDDY", "Dr. Reddy's Laboratories"),
    _nse("DIVISLAB", "Divi's Laboratories"),
    _nse("APOLLOHOSP", "Apollo Hospitals Enterprise"),
    _nse("BAJAJFINSV", "Bajaj Finserv"),
    _nse("BAJAJ-AUTO", "Bajaj Auto"),
    _nse("HEROMOTOCO", "Hero MotoCorp"),
    _nse("EICHERMOT", "Eicher Motors"),
    _nse("M&M", "Mahindra & Mahindra"),
    _nse("BRITANNIA", "Britannia Industries"),
    _nse("TECHM", "Tech Mahindra"),
    _nse("INDUSINDBK", "IndusInd Bank"),
    _nse("SBILIFE", "SBI Life Insurance"),
    _nse("HDFCLIFE", "HDFC Life Insurance"),
    _nse("TATACONSUM", "Tata Consumer Products"),
    _nse("BPCL", "Bharat Petroleum Corporation"),
    _nse("SHRIRAMFIN", "Shriram Finance"),
    _nse("LTIM", "LTIMindtree"),
)


class InstrumentRegistry:
    """Lookup, search and availability for the supported universe."""

    def __init__(self, instruments: tuple[Instrument, ...] = NSE_INSTRUMENTS) -> None:
        self._by_symbol: dict[str, Instrument] = {
            instrument.symbol.upper(): instrument for instrument in instruments
        }
        self._instruments = instruments
        #: symbol -> whether the provider served it. Populated on demand.
        self._availability: dict[str, bool] = {}

    # -- catalogue -------------------------------------------------------

    def all(self) -> list[Instrument]:
        return list(self._instruments)

    def get(self, symbol: str | None) -> Instrument | None:
        if symbol is None:
            return None
        return self._by_symbol.get(symbol.strip().upper())

    def is_known(self, symbol: str | None) -> bool:
        return self.get(symbol) is not None

    def search(self, query: str | None = None, *, limit: int = 50) -> list[Instrument]:
        """Match on symbol or company name, case-insensitively.

        Symbol matches rank above company-name matches, and a prefix match
        ranks above a substring one, so typing ``TCS`` puts Tata Consultancy
        first rather than any company whose name happens to contain it.
        """
        if not query or not query.strip():
            return self.all()[:limit]

        needle = query.strip().lower()
        scored: list[tuple[int, Instrument]] = []

        for instrument in self._instruments:
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

    async def verify(self, symbol: str, provider) -> bool:
        """Ask the provider whether it can actually serve this symbol.

        Cached per process: a symbol is probed at most once, because the answer
        is a property of the feed rather than of the moment.
        """
        instrument = self.get(symbol)
        if instrument is None:
            return False

        cached = self.cached_availability(instrument.symbol)
        if cached is not None:
            return cached

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


def resolve_instrument(symbol: str | None):
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
