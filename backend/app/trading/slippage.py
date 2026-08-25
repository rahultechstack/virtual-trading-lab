"""Slippage.

The gap between the price you aimed at and the price you got, caused by the
book moving while the order is in flight. Modelled as always **adverse**: a buy
fills higher than intended, a sell lower. A model that could help you would
flatter every backtest built on it.

Pure arithmetic -- no database, no order, no session.
"""

from dataclasses import dataclass
from decimal import Decimal
from enum import StrEnum

from app.core.config import settings
from app.trading.pnl import to_money

_BPS = Decimal("10000")
_PERCENT = Decimal("100")


class SlippageType(StrEnum):
    NONE = "NONE"
    #: A fixed number of basis points against the fill.
    FIXED_BPS = "FIXED_BPS"
    #: A fixed percentage against the fill.
    PERCENT = "PERCENT"


@dataclass(frozen=True)
class SlippageResult:
    """The effect of slippage on one fill."""

    base_price: Decimal
    slipped_price: Decimal
    #: Per-share adverse movement. Never negative.
    price_impact: Decimal
    #: Total money lost to slippage across the whole fill.
    cost: Decimal


class SlippageModel:
    """Applies an adverse price adjustment to a fill."""

    def __init__(
        self,
        *,
        slippage_type: SlippageType = SlippageType.FIXED_BPS,
        basis_points: Decimal = Decimal("2"),
        percent: Decimal = Decimal("0"),
    ) -> None:
        self.slippage_type = slippage_type
        self.basis_points = basis_points
        self.percent = percent

    @classmethod
    def from_settings(cls) -> "SlippageModel":
        return cls(
            slippage_type=SlippageType(settings.SLIPPAGE_MODEL),
            basis_points=settings.SLIPPAGE_BPS,
            percent=settings.SLIPPAGE_PERCENT,
        )

    @classmethod
    def disabled(cls) -> "SlippageModel":
        return cls(slippage_type=SlippageType.NONE)

    @property
    def is_enabled(self) -> bool:
        return self.slippage_type is not SlippageType.NONE

    def rate(self) -> Decimal:
        """Adverse movement as a fraction of price."""
        if self.slippage_type is SlippageType.FIXED_BPS:
            return self.basis_points / _BPS
        if self.slippage_type is SlippageType.PERCENT:
            return self.percent / _PERCENT
        return Decimal("0")

    def apply(
        self, *, base_price: Decimal, direction: int, quantity: int
    ) -> SlippageResult:
        """Move ``base_price`` against the trader.

        Args:
            base_price: Price before slippage.
            direction: ``+1`` for a buy, ``-1`` for a sell.
            quantity: Fill size, used to total the cost.

        A buy is pushed up and a sell down, both by ``rate()``.
        """
        rate = self.rate()
        if rate == 0 or base_price <= 0:
            return SlippageResult(
                base_price=base_price,
                slipped_price=base_price,
                price_impact=Decimal("0.00"),
                cost=Decimal("0.00"),
            )

        adjustment = base_price * rate * Decimal(direction)
        slipped = to_money(base_price + adjustment)
        impact = abs(slipped - base_price)

        return SlippageResult(
            base_price=base_price,
            slipped_price=slipped,
            price_impact=impact,
            cost=to_money(impact * Decimal(quantity)),
        )
