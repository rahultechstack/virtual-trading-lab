"""Instrument value types.

The vocabulary the rest of the platform dispatches on. Separated from both the
catalogue (``catalogue.py``, the data) and the registry (``instruments.py``,
the lookup logic) so that all three can import each other without a cycle.

**Adding an asset class starts here** -- add the ``AssetClass`` member, then
register it in the four dispatch tables listed in ``CONFIGURATION.md``.
"""

from dataclasses import dataclass
from decimal import Decimal
from enum import StrEnum


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
