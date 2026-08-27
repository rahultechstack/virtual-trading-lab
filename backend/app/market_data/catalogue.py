"""**THE SUPPORTED INSTRUMENT CATALOGUE.**

===========================================================================
 THIS IS THE ONE FILE TO EDIT TO ADD OR REMOVE A TRADABLE STOCK OR COIN.

   Add an NSE stock:   _nse("WIPRO", "Wipro")           -> NSE_INSTRUMENTS
   Add a coin:         _crypto("BTC", "Bitcoin")        -> CRYPTO_INSTRUMENTS

 Then restart the backend. Nothing else needs changing -- the API, the
 picker, the calendars, the fee rules and the provider routing all read
 from here.
===========================================================================

Data only: no lookup logic, no validation, no I/O. The registry that searches
and validates against this catalogue lives in ``instruments.py``.

**Only list what the provider actually serves.** An instrument is tradable
only when it is both listed here *and* served by the feed configured for its
asset class. ``GET /instruments/{symbol}`` verifies the second half on demand,
and a ``network``-marked test checks every catalogued coin against the live
feed. Listing something the feed cannot serve would advertise an instrument
that fails the moment anyone selects it.

**Why curated rather than the full exchange listing.** Neither configured
provider has an instrument-discovery endpoint, so there is nothing to
enumerate from.
"""

from app.market_data.instrument_types import (
    AssetClass,
    Instrument,
    InstrumentType,
    SATOSHI,
    WHOLE_UNITS,
)


def _nse(symbol: str, company_name: str) -> Instrument:
    """An NSE cash-market equity. Whole shares, NSE session hours."""
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
    """A cryptocurrency. Fractional to 8dp, open 24/7.

    Crypto has no single listing venue. "CRYPTO" is the platform's own code
    for the global spot market and is what lands on every order, trade,
    position and automatic-order row.
    """
    return Instrument(
        symbol=symbol,
        company_name=name,
        asset_class=AssetClass.CRYPTO,
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
