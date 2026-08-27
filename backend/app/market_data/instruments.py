"""The tradable instrument universe, across asset classes.

The backend is the source of truth for what this platform trades. An
instrument is tradable only when it is **both** in the catalogue below and
served by the provider configured for its asset class -- ``data_available`` is
verified against that provider rather than assumed, and cached so the check
costs one upstream call per symbol per process.

**Asset classes.** Everything downstream dispatches on ``Instrument
.asset_class`` rather than on the symbol:

    Instrument
        |
        v
    AssetClass  --> MarketCalendar        app/markets/            when may it trade
        |       --> MarketDataProvider    app/market_data/router  where prices come from
        |       --> quantity rules        normalise_quantity()    what sizes are legal
        +-------> FeeSchedule             app/trading/fees.py     what it costs

Adding ETF or INDEX later means adding an ``AssetClass`` member and one entry
in each of those four tables. It does not mean touching the trading engine.

**Why a curated catalogue.** Neither configured provider has an
instrument-discovery endpoint, so there is nothing to enumerate from. Listing
every NSE symbol or every coin would advertise instruments the feed cannot
actually serve, which is exactly what must not happen. Every entry below was
verified against the live feed before being added.
"""

from dataclasses import dataclass
from decimal import Decimal
from enum import StrEnum

from app.core.logging import get_logger

logger = get_logger(__name__)


class AssetClass(StrEnum):
    """The dispatch key for market rules, data, fees and quantity handling.

    Deliberately coarse. ``STOCK`` covers anything trading on an equity
    exchange under that exchange's calendar and statutory charges; ``CRYPTO``
    covers anything trading continuously with no exchange calendar. ETF and
    INDEX would share ``STOCK``'s calendar but want their own fee rules, which
    is why the fee table is keyed separately from the calendar table.
    """

    STOCK = "STOCK"
    CRYPTO = "CRYPTO"


class InstrumentType(StrEnum):
    """The finer label shown to users, inside an asset class."""

    EQUITY = "EQUITY"
    CRYPTOCURRENCY = "CRYPTOCURRENCY"


#: Stocks trade in whole shares. This platform models the NSE cash segment,
#: which has no fractional ownership.
WHOLE_UNITS = Decimal("1")

#: Crypto divides to eight decimal places -- one satoshi. The ledger stores
#: quantities at exactly this precision (``QUANTITY`` in app/models/trading.py).
SATOSHI = Decimal("0.00000001")


@dataclass(frozen=True)
class Instrument:
    """One tradable instrument.

    ``data_available`` is deliberately not a field here -- availability is a
    property of the *provider*, not of the listing, so it is resolved per
    request by :class:`InstrumentRegistry` and cached.
    """

    symbol: str
    company_name: str
    asset_class: AssetClass
    exchange: str
    #: Human label for the venue or segment, e.g. "NSE Cash Market".
    market: str
    #: Human label for the schedule. The authoritative answer comes from the
    #: instrument's ``MarketCalendar``; this is the caption for it.
    trading_hours: str
    instrument_type: InstrumentType
    #: Smallest tradable increment. 1 for stocks, 0.00000001 for crypto.
    quantity_step: Decimal = WHOLE_UNITS

    @property
    def display_name(self) -> str:
        return f"{self.exchange}:{self.symbol}"

    @property
    def is_fractional(self) -> bool:
        """Whether this instrument may be traded in fractions of a unit."""
        return self.quantity_step < WHOLE_UNITS

    @property
    def quantity_precision(self) -> int:
        """Decimal places implied by ``quantity_step``."""
        exponent = self.quantity_step.normalize().as_tuple().exponent
        return max(0, -int(exponent))


def _nse(symbol: str, company_name: str) -> Instrument:
    return Instrument(
        symbol=symbol,
        company_name=company_name,
        asset_class=AssetClass.STOCK,
        exchange="NSE",
        market="NSE Cash Market",
        trading_hours="09:15-15:30 IST, Mon-Fri",
        instrument_type=InstrumentType.EQUITY,
        quantity_step=WHOLE_UNITS,
    )


def _crypto(symbol: str, name: str) -> Instrument:
    return Instrument(
        symbol=symbol,
        company_name=name,
        asset_class=AssetClass.CRYPTO,
        # Crypto has no single listing venue. "CRYPTO" is the platform's own
        # code for the global spot market and is what lands on every order,
        # trade, position and automatic-order row.
        exchange="CRYPTO",
        market="Global Crypto Spot",
        trading_hours="24/7",
        instrument_type=InstrumentType.CRYPTOCURRENCY,
        quantity_step=SATOSHI,
    )


#: Curated NSE equities the equity provider serves. Ordered by how likely they
#: are to be wanted, not alphabetically, so the default dropdown is useful.
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

#: Cryptocurrencies the crypto provider serves, priced in INR.
#:
#: Every entry was verified against the live feed before being listed, and
#: ``GET /instruments/{symbol}`` re-verifies on demand.
#:
#: **Sub-paisa assets are excluded.** This ledger denominates prices in paise
#: (``Numeric(18, 2)``), so an asset trading below Rs 0.01 -- SHIB at roughly
#: Rs 0.0005, for instance -- cannot be represented without rounding its price
#: to zero. Such assets are left out rather than listed and silently broken.
#: Widening the price columns is the change that would admit them.
CRYPTO_INSTRUMENTS: tuple[Instrument, ...] = (
    _crypto("BTC", "Bitcoin"),
    _crypto("ETH", "Ethereum"),
    _crypto("BNB", "BNB"),
    _crypto("SOL", "Solana"),
    _crypto("XRP", "XRP"),
    _crypto("ADA", "Cardano"),
    _crypto("DOGE", "Dogecoin"),
    _crypto("TRX", "TRON"),
    _crypto("LTC", "Litecoin"),
    _crypto("DOT", "Polkadot"),
    _crypto("AVAX", "Avalanche"),
    _crypto("LINK", "Chainlink"),
    _crypto("USDT", "Tether"),
)

#: The whole universe. Stocks first, so an unfiltered listing opens on equities.
ALL_INSTRUMENTS: tuple[Instrument, ...] = NSE_INSTRUMENTS + CRYPTO_INSTRUMENTS


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
