"""Indian equity trading charges.

Every statutory and broker charge lives here and nowhere else. The calculator
is pure -- it takes a side, a quantity and a price and returns a breakdown, so
it can be tested and audited without a database, a session or an order.

**Charges modelled** (NSE cash segment):

| Charge              | Intraday                    | Delivery                   |
| ------------------- | --------------------------- | -------------------------- |
| Brokerage           | % of turnover, capped/order | usually zero               |
| STT                 | sell side only              | both sides, higher rate    |
| Exchange txn charge | both sides                  | both sides                 |
| SEBI turnover fee   | both sides                  | both sides                 |
| Stamp duty          | buy side only               | buy side only, higher rate |
| GST                 | on brokerage + txn + SEBI   | same                       |
| DP charges          | none                        | flat, sell side only       |

**Rounding.** STT and stamp duty are rounded to the nearest rupee, which is
what appears on a real contract note. Everything else is kept to paise.

**Rates change.** Every rate is a setting, not a literal -- exchange transaction
charges and stamp duty in particular have been revised repeatedly. The defaults
reflect a typical discount broker on NSE; verify them against your broker's
current schedule before treating the numbers as authoritative.
"""

from dataclasses import dataclass
from decimal import ROUND_HALF_UP, Decimal
from enum import StrEnum

from app.core.config import settings
from app.models.enums import OrderSide
from app.trading.pnl import to_money

_RUPEE = Decimal("1")
_PERCENT = Decimal("100")


class Segment(StrEnum):
    """Which charge schedule applies.

    ``INTRADAY`` is the default because short selling in the Indian cash
    market must be squared off the same day, so the platform's short support
    only makes sense under intraday rules.
    """

    INTRADAY = "INTRADAY"
    DELIVERY = "DELIVERY"


def to_rupee(value: Decimal) -> Decimal:
    """Round to the nearest whole rupee, as a contract note does."""
    return value.quantize(_RUPEE, rounding=ROUND_HALF_UP)


@dataclass(frozen=True)
class ChargeBreakdown:
    """Itemised charges for one fill. All values are positive costs."""

    brokerage: Decimal = Decimal("0.00")
    stt: Decimal = Decimal("0.00")
    exchange_charges: Decimal = Decimal("0.00")
    sebi_charges: Decimal = Decimal("0.00")
    stamp_duty: Decimal = Decimal("0.00")
    gst: Decimal = Decimal("0.00")
    dp_charges: Decimal = Decimal("0.00")

    @property
    def total(self) -> Decimal:
        return to_money(
            self.brokerage
            + self.stt
            + self.exchange_charges
            + self.sebi_charges
            + self.stamp_duty
            + self.gst
            + self.dp_charges
        )

    @classmethod
    def zero(cls) -> "ChargeBreakdown":
        return cls()


class FeeCalculator:
    """Computes the charges on a single fill."""

    def __init__(
        self,
        *,
        segment: Segment = Segment.INTRADAY,
        enabled: bool = True,
        brokerage_percent: Decimal = Decimal("0.03"),
        brokerage_max_per_order: Decimal | None = Decimal("20"),
        stt_intraday_sell_percent: Decimal = Decimal("0.025"),
        stt_delivery_percent: Decimal = Decimal("0.1"),
        exchange_txn_percent: Decimal = Decimal("0.00297"),
        sebi_charges_percent: Decimal = Decimal("0.0001"),
        stamp_duty_intraday_buy_percent: Decimal = Decimal("0.003"),
        stamp_duty_delivery_buy_percent: Decimal = Decimal("0.015"),
        gst_percent: Decimal = Decimal("18"),
        dp_charges_per_sell: Decimal = Decimal("0"),
    ) -> None:
        self.segment = segment
        self.enabled = enabled
        self.brokerage_percent = brokerage_percent
        self.brokerage_max_per_order = brokerage_max_per_order
        self.stt_intraday_sell_percent = stt_intraday_sell_percent
        self.stt_delivery_percent = stt_delivery_percent
        self.exchange_txn_percent = exchange_txn_percent
        self.sebi_charges_percent = sebi_charges_percent
        self.stamp_duty_intraday_buy_percent = stamp_duty_intraday_buy_percent
        self.stamp_duty_delivery_buy_percent = stamp_duty_delivery_buy_percent
        self.gst_percent = gst_percent
        self.dp_charges_per_sell = dp_charges_per_sell

    # -- construction ----------------------------------------------------

    @classmethod
    def from_settings(cls) -> "FeeCalculator":
        return cls(
            segment=Segment(settings.EXECUTION_SEGMENT),
            enabled=settings.CHARGES_ENABLED,
            brokerage_percent=settings.BROKERAGE_PERCENT,
            brokerage_max_per_order=settings.BROKERAGE_MAX_PER_ORDER,
            stt_intraday_sell_percent=settings.STT_INTRADAY_SELL_PERCENT,
            stt_delivery_percent=settings.STT_DELIVERY_PERCENT,
            exchange_txn_percent=settings.EXCHANGE_TXN_PERCENT,
            sebi_charges_percent=settings.SEBI_CHARGES_PERCENT,
            stamp_duty_intraday_buy_percent=settings.STAMP_DUTY_INTRADAY_BUY_PERCENT,
            stamp_duty_delivery_buy_percent=settings.STAMP_DUTY_DELIVERY_BUY_PERCENT,
            gst_percent=settings.GST_PERCENT,
            dp_charges_per_sell=settings.DP_CHARGES_PER_SELL,
        )

    @classmethod
    def disabled(cls) -> "FeeCalculator":
        """A calculator that charges nothing.

        Used by tests that isolate position accounting from fee arithmetic.
        """
        return cls(enabled=False)

    # -- calculation -----------------------------------------------------

    def calculate(
        self, *, side: OrderSide, quantity: int, price: Decimal
    ) -> ChargeBreakdown:
        """Itemise the charges on one fill."""
        if not self.enabled or quantity <= 0 or price <= 0:
            return ChargeBreakdown.zero()

        turnover = price * Decimal(quantity)
        is_buy = side.direction > 0

        brokerage = self._brokerage(turnover)
        stt = self._stt(turnover, is_buy=is_buy)
        exchange = self._percent_of(turnover, self.exchange_txn_percent)
        sebi = self._percent_of(turnover, self.sebi_charges_percent)
        stamp_duty = self._stamp_duty(turnover, is_buy=is_buy)
        dp = self._dp_charges(is_buy=is_buy)

        # GST applies to the broker's and the exchange's fees, not to the
        # statutory taxes (STT and stamp duty are not GST-bearing).
        gst = self._percent_of(brokerage + exchange + sebi, self.gst_percent)

        return ChargeBreakdown(
            brokerage=brokerage,
            stt=stt,
            exchange_charges=exchange,
            sebi_charges=sebi,
            stamp_duty=stamp_duty,
            gst=gst,
            dp_charges=dp,
        )

    # -- components ------------------------------------------------------

    @staticmethod
    def _percent_of(base: Decimal, percent: Decimal) -> Decimal:
        return to_money(base * percent / _PERCENT)

    def _brokerage(self, turnover: Decimal) -> Decimal:
        """Percentage of turnover, capped per order where a cap is configured."""
        charge = turnover * self.brokerage_percent / _PERCENT
        if self.brokerage_max_per_order is not None:
            charge = min(charge, self.brokerage_max_per_order)
        return to_money(charge)

    def _stt(self, turnover: Decimal, *, is_buy: bool) -> Decimal:
        """Securities Transaction Tax, rounded to the nearest rupee.

        Intraday charges the sell leg only; delivery charges both.
        """
        if self.segment is Segment.INTRADAY:
            if is_buy:
                return Decimal("0.00")
            rate = self.stt_intraday_sell_percent
        else:
            rate = self.stt_delivery_percent
        return to_rupee(turnover * rate / _PERCENT)

    def _stamp_duty(self, turnover: Decimal, *, is_buy: bool) -> Decimal:
        """Stamp duty, buy side only, rounded to the nearest rupee."""
        if not is_buy:
            return Decimal("0.00")
        rate = (
            self.stamp_duty_intraday_buy_percent
            if self.segment is Segment.INTRADAY
            else self.stamp_duty_delivery_buy_percent
        )
        return to_rupee(turnover * rate / _PERCENT)

    def _dp_charges(self, *, is_buy: bool) -> Decimal:
        """Depository charges: a flat fee on delivery sells only."""
        if self.segment is Segment.DELIVERY and not is_buy:
            return to_money(self.dp_charges_per_sell)
        return Decimal("0.00")
