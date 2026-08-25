"""Bid/ask spread.

A reference price is a *mid* price -- the midpoint between the best bid and the
best ask. Nobody trades at the mid: buyers lift the ask, sellers hit the bid.
The half-spread each side is a real, unavoidable cost of crossing.

This matters here because the configured market-data provider supplies no
order-book depth (``bid`` and ``ask`` come back null -- see the README), so the
spread has to be modelled rather than observed.

Pure arithmetic -- no database, no order, no session.
"""

from dataclasses import dataclass
from decimal import Decimal

from app.core.config import settings
from app.trading.pnl import to_money

_BPS = Decimal("10000")
_TWO = Decimal("2")


@dataclass(frozen=True)
class BidAsk:
    """A two-sided quote derived from a mid price."""

    mid: Decimal
    bid: Decimal
    ask: Decimal

    @property
    def spread(self) -> Decimal:
        """Full quoted spread, ask minus bid."""
        return to_money(self.ask - self.bid)

    def price_for(self, direction: int) -> Decimal:
        """The side a trade crosses: buys lift the ask, sells hit the bid."""
        return self.ask if direction > 0 else self.bid


@dataclass(frozen=True)
class SpreadResult:
    """The effect of crossing the spread on one fill."""

    quote: BidAsk
    fill_price: Decimal
    #: Per-share half-spread paid. Never negative.
    price_impact: Decimal
    #: Total money lost to the spread across the whole fill.
    cost: Decimal


class SpreadModel:
    """Derives a two-sided quote from a mid price."""

    def __init__(self, *, basis_points: Decimal = Decimal("2")) -> None:
        #: Full spread in basis points; half is applied to each side.
        self.basis_points = basis_points

    @classmethod
    def from_settings(cls) -> "SpreadModel":
        return cls(basis_points=settings.SPREAD_BPS)

    @classmethod
    def disabled(cls) -> "SpreadModel":
        return cls(basis_points=Decimal("0"))

    @property
    def is_enabled(self) -> bool:
        return self.basis_points > 0

    def quote(self, mid_price: Decimal) -> BidAsk:
        """Build bid and ask around ``mid_price``.

        ``basis_points`` is the *full* spread, so half is applied either side
        and the mid stays exactly where it was.
        """
        half = mid_price * (self.basis_points / _BPS) / _TWO
        return BidAsk(
            mid=mid_price,
            bid=to_money(mid_price - half),
            ask=to_money(mid_price + half),
        )

    def apply(
        self, *, mid_price: Decimal, direction: int, quantity: int
    ) -> SpreadResult:
        """Cross the spread in ``direction`` and report the cost."""
        quote = self.quote(mid_price)
        fill_price = quote.price_for(direction)
        impact = abs(fill_price - mid_price)

        return SpreadResult(
            quote=quote,
            fill_price=fill_price,
            price_impact=impact,
            cost=to_money(impact * Decimal(quantity)),
        )
