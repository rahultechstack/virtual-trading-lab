"""Fee, slippage and spread models, tested in isolation.

All three are pure, so none of this touches a database, a session or an order.
Expected values are worked by hand in the docstrings.
"""

from decimal import Decimal

import pytest

from app.models.enums import OrderSide
from app.trading.fees import ChargeBreakdown, FeeCalculator, Segment, to_rupee
from app.trading.slippage import SlippageModel, SlippageType
from app.trading.spread import SpreadModel

D = Decimal


# ==========================================================================
# Bid/ask spread
# ==========================================================================


def test_spread_is_split_evenly_around_the_mid():
    """20 bps on 1000: half-spread 1.00 either side -> bid 999, ask 1001."""
    quote = SpreadModel(basis_points=D("20")).quote(D("1000"))

    assert quote.mid == D("1000")
    assert quote.bid == D("999.00")
    assert quote.ask == D("1001.00")
    assert quote.spread == D("2.00")


def test_buys_lift_the_ask_and_sells_hit_the_bid():
    quote = SpreadModel(basis_points=D("20")).quote(D("1000"))

    assert quote.price_for(1) == quote.ask
    assert quote.price_for(-1) == quote.bid


def test_spread_cost_scales_with_quantity():
    """Half-spread 1.00 x 100 shares = 100.00."""
    result = SpreadModel(basis_points=D("20")).apply(
        mid_price=D("1000"), direction=1, quantity=100
    )

    assert result.fill_price == D("1001.00")
    assert result.price_impact == D("1.00")
    assert result.cost == D("100.00")


def test_spread_hurts_both_directions_equally():
    model = SpreadModel(basis_points=D("20"))

    buy = model.apply(mid_price=D("1000"), direction=1, quantity=100)
    sell = model.apply(mid_price=D("1000"), direction=-1, quantity=100)

    assert buy.cost == sell.cost == D("100.00")
    assert buy.fill_price > D("1000") and sell.fill_price < D("1000")


def test_disabled_spread_fills_at_the_mid():
    result = SpreadModel.disabled().apply(
        mid_price=D("1000"), direction=1, quantity=100
    )

    assert result.fill_price == D("1000")
    assert result.cost == D("0.00")
    assert SpreadModel.disabled().is_enabled is False


# ==========================================================================
# Slippage
# ==========================================================================


def test_slippage_pushes_a_buy_up():
    """10 bps on 1000 = 1.00 adverse."""
    result = SlippageModel(basis_points=D("10")).apply(
        base_price=D("1000"), direction=1, quantity=100
    )

    assert result.slipped_price == D("1001.00")
    assert result.price_impact == D("1.00")
    assert result.cost == D("100.00")


def test_slippage_pushes_a_sell_down():
    result = SlippageModel(basis_points=D("10")).apply(
        base_price=D("1000"), direction=-1, quantity=100
    )

    assert result.slipped_price == D("999.00")
    assert result.price_impact == D("1.00")
    assert result.cost == D("100.00")


def test_slippage_is_never_favourable():
    """Whichever way you trade, the price moves against you."""
    model = SlippageModel(basis_points=D("25"))

    buy = model.apply(base_price=D("1000"), direction=1, quantity=1)
    sell = model.apply(base_price=D("1000"), direction=-1, quantity=1)

    assert buy.slipped_price > D("1000")
    assert sell.slipped_price < D("1000")
    assert buy.cost >= 0 and sell.cost >= 0


def test_percent_slippage_model():
    """0.5% of 1000 = 5.00."""
    model = SlippageModel(slippage_type=SlippageType.PERCENT, percent=D("0.5"))

    result = model.apply(base_price=D("1000"), direction=1, quantity=10)

    assert result.slipped_price == D("1005.00")
    assert result.cost == D("50.00")


def test_disabled_slippage_leaves_the_price_alone():
    result = SlippageModel.disabled().apply(
        base_price=D("1000"), direction=1, quantity=100
    )

    assert result.slipped_price == D("1000")
    assert result.cost == D("0.00")
    assert SlippageModel.disabled().is_enabled is False


# ==========================================================================
# Charges
# ==========================================================================


@pytest.fixture
def fees() -> FeeCalculator:
    """Default intraday schedule, so the arithmetic below is reproducible."""
    return FeeCalculator(segment=Segment.INTRADAY)


def test_intraday_buy_charges(fees):
    """100 @ 1000 = 100,000 turnover.

    brokerage  min(0.03% = 30, cap 20)   = 20.00
    STT        buy side, intraday        =  0.00
    exchange   0.00297%                  =  2.97
    SEBI       0.0001%                   =  0.10
    stamp duty 0.003%, nearest rupee     =  3.00
    GST        18% of (20 + 2.97 + 0.10) =  4.15
    total                                = 30.22
    """
    charges = fees.calculate(side=OrderSide.BUY, quantity=100, price=D("1000"))

    assert charges.brokerage == D("20.00")
    assert charges.stt == D("0.00")
    assert charges.exchange_charges == D("2.97")
    assert charges.sebi_charges == D("0.10")
    assert charges.stamp_duty == D("3.00")
    assert charges.gst == D("4.15")
    assert charges.total == D("30.22")


def test_intraday_sell_charges_stt_but_no_stamp_duty(fees):
    """STT 0.025% of 100,000 = 25; stamp duty is buy-side only."""
    charges = fees.calculate(side=OrderSide.SELL, quantity=100, price=D("1000"))

    assert charges.stt == D("25.00")
    assert charges.stamp_duty == D("0.00")
    assert charges.total == D("52.22")


def test_short_sell_is_charged_as_a_sell(fees):
    sell = fees.calculate(side=OrderSide.SELL, quantity=100, price=D("1000"))
    short = fees.calculate(side=OrderSide.SHORT_SELL, quantity=100, price=D("1000"))

    assert short == sell


def test_buy_to_cover_is_charged_as_a_buy(fees):
    buy = fees.calculate(side=OrderSide.BUY, quantity=100, price=D("1000"))
    cover = fees.calculate(side=OrderSide.BUY_TO_COVER, quantity=100, price=D("1000"))

    assert cover == buy


def test_brokerage_is_capped_per_order(fees):
    """0.03% of 10,00,000 would be 300, but the cap is 20."""
    charges = fees.calculate(side=OrderSide.BUY, quantity=1000, price=D("1000"))

    assert charges.brokerage == D("20.00")


def test_brokerage_is_percentage_based_below_the_cap(fees):
    """0.03% of 10,000 = 3.00, under the 20 cap."""
    charges = fees.calculate(side=OrderSide.BUY, quantity=10, price=D("1000"))

    assert charges.brokerage == D("3.00")


def test_brokerage_without_a_cap_is_uncapped():
    calculator = FeeCalculator(brokerage_max_per_order=None)

    charges = calculator.calculate(side=OrderSide.BUY, quantity=1000, price=D("1000"))

    assert charges.brokerage == D("300.00")


def test_gst_excludes_statutory_taxes(fees):
    """GST applies to brokerage, exchange and SEBI -- never to STT or stamp duty."""
    charges = fees.calculate(side=OrderSide.SELL, quantity=100, price=D("1000"))

    expected = (
        (charges.brokerage + charges.exchange_charges + charges.sebi_charges)
        * D("18")
        / D("100")
    )
    assert charges.gst == expected.quantize(D("0.01"))


def test_stt_and_stamp_duty_round_to_whole_rupees(fees):
    """Contract notes round these two; the rest stay in paise."""
    charges = fees.calculate(side=OrderSide.SELL, quantity=37, price=D("1234.56"))

    assert charges.stt == charges.stt.to_integral_value()
    charges_buy = fees.calculate(side=OrderSide.BUY, quantity=37, price=D("1234.56"))
    assert charges_buy.stamp_duty == charges_buy.stamp_duty.to_integral_value()


def test_delivery_charges_stt_on_both_sides():
    calculator = FeeCalculator(segment=Segment.DELIVERY)

    buy = calculator.calculate(side=OrderSide.BUY, quantity=100, price=D("1000"))
    sell = calculator.calculate(side=OrderSide.SELL, quantity=100, price=D("1000"))

    # 0.1% of 100,000 = 100 on each leg.
    assert buy.stt == D("100.00")
    assert sell.stt == D("100.00")


def test_delivery_applies_dp_charges_on_the_sell_only():
    calculator = FeeCalculator(
        segment=Segment.DELIVERY, dp_charges_per_sell=D("15.34")
    )

    buy = calculator.calculate(side=OrderSide.BUY, quantity=100, price=D("1000"))
    sell = calculator.calculate(side=OrderSide.SELL, quantity=100, price=D("1000"))

    assert buy.dp_charges == D("0.00")
    assert sell.dp_charges == D("15.34")


def test_delivery_stamp_duty_is_higher_than_intraday():
    intraday = FeeCalculator(segment=Segment.INTRADAY).calculate(
        side=OrderSide.BUY, quantity=100, price=D("1000")
    )
    delivery = FeeCalculator(segment=Segment.DELIVERY).calculate(
        side=OrderSide.BUY, quantity=100, price=D("1000")
    )

    assert delivery.stamp_duty > intraday.stamp_duty


def test_charges_scale_with_turnover(fees):
    small = fees.calculate(side=OrderSide.SELL, quantity=10, price=D("1000"))
    large = fees.calculate(side=OrderSide.SELL, quantity=1000, price=D("1000"))

    assert large.total > small.total
    assert large.exchange_charges > small.exchange_charges
    assert large.stt > small.stt


def test_rounding_makes_charges_slightly_non_linear(fees):
    """Not a bug -- it is what a contract note does.

    10 shares @ 1000 is 10,000 turnover. STT at 0.025% is 2.50, rounded up to
    3; exchange charges at 0.00297% are 0.297, rounded to 0.30. Scaling the
    trade 100x gives 250 and 29.70 exactly, because at that size the rounding
    no longer bites.
    """
    small = fees.calculate(side=OrderSide.SELL, quantity=10, price=D("1000"))
    large = fees.calculate(side=OrderSide.SELL, quantity=1000, price=D("1000"))

    assert small.stt == D("3")
    assert large.stt == D("250")
    assert small.exchange_charges == D("0.30")
    assert large.exchange_charges == D("29.70")


def test_disabled_calculator_charges_nothing():
    charges = FeeCalculator.disabled().calculate(
        side=OrderSide.BUY, quantity=1000, price=D("1000")
    )

    assert charges == ChargeBreakdown.zero()
    assert charges.total == D("0.00")


@pytest.mark.parametrize(("quantity", "price"), [(0, "1000"), (100, "0")])
def test_degenerate_inputs_charge_nothing(fees, quantity, price):
    charges = fees.calculate(
        side=OrderSide.BUY, quantity=quantity, price=D(price)
    )

    assert charges.total == D("0.00")


def test_total_is_the_sum_of_the_parts(fees):
    charges = fees.calculate(side=OrderSide.SELL, quantity=250, price=D("1437.65"))

    assert charges.total == (
        charges.brokerage
        + charges.stt
        + charges.exchange_charges
        + charges.sebi_charges
        + charges.stamp_duty
        + charges.gst
        + charges.dp_charges
    )


def test_rupee_rounding_is_half_up():
    assert to_rupee(D("24.5")) == D("25")
    assert to_rupee(D("24.49")) == D("24")


def test_calculator_reads_its_rates_from_settings():
    """Every rate is configuration, not a literal."""
    calculator = FeeCalculator.from_settings()

    assert calculator.gst_percent == D("18")
    assert calculator.brokerage_max_per_order == D("20")
    assert calculator.segment is Segment.INTRADAY
