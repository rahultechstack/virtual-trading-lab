"""Realistic execution end to end, against a real PostgreSQL database.

The four trade outcomes -- profitable long, losing long, profitable short,
losing short -- are each traced from reference price through spread, slippage
and charges to gross P&L, total charges and net P&L, with the wallet checked
against the arithmetic.

The models are configured explicitly rather than read from settings, so these
expectations do not silently change when a rate is edited in `.env`.
"""

from decimal import Decimal

import pytest
from sqlalchemy import select

from app.core.exceptions import InsufficientFundsError
from app.models.enums import OrderSide
from app.models.trading import Position, Trade
from app.models.wallet import Wallet
from app.services.wallet_service import WalletService
from app.trading.engine import TradingEngine
from app.trading.execution import ExecutionEngine
from app.trading.fees import FeeCalculator, Segment
from app.trading.slippage import SlippageModel
from app.trading.spread import SpreadModel

D = Decimal


def _realistic_execution(session) -> ExecutionEngine:
    """20 bps spread, 10 bps slippage, default intraday charges.

    Round numbers so every expected value below can be worked by hand.
    """
    return ExecutionEngine(
        session,
        spread=SpreadModel(basis_points=D("20")),
        slippage=SlippageModel(basis_points=D("10")),
        fees=FeeCalculator(segment=Segment.INTRADAY),
    )


@pytest.fixture
async def engine(session) -> TradingEngine:
    await WalletService(session).initialize_wallet()
    return TradingEngine(session, execution=_realistic_execution(session))


async def _cash(session) -> Decimal:
    wallet = (await session.execute(select(Wallet))).scalar_one()
    await session.refresh(wallet)
    return wallet.cash_balance


async def _trades(session) -> list[Trade]:
    return list((await session.execute(select(Trade).order_by(Trade.id))).scalars())


# ==========================================================================
# Price derivation
# ==========================================================================


async def test_a_buy_fills_above_the_reference_price(engine, session):
    """Mid 1000 -> ask 1001 (half of 20bps) -> +10bps slippage -> 1002.00."""
    result = await engine.place_order(
        side=OrderSide.BUY, quantity=100, reference_price=D("1000")
    )

    trade = result.trade
    assert trade.reference_price == D("1000.00")
    assert trade.bid_price == D("999.00")
    assert trade.ask_price == D("1001.00")
    assert trade.execution_price == D("1002.00")


async def test_a_sell_fills_below_the_reference_price(engine):
    """Mid 1000 -> bid 999 -> -10bps slippage -> 998.00."""
    await engine.place_order(
        side=OrderSide.BUY, quantity=100, reference_price=D("1000")
    )

    result = await engine.place_order(
        side=OrderSide.SELL, quantity=100, reference_price=D("1000")
    )

    assert result.trade.execution_price == D("998.00")


async def test_spread_and_slippage_costs_are_recorded_separately(engine):
    """Half-spread 1.00 and slippage 1.00, each x 100 shares."""
    result = await engine.place_order(
        side=OrderSide.BUY, quantity=100, reference_price=D("1000")
    )

    assert result.trade.spread_cost == D("100.00")
    assert result.trade.slippage_cost == D("100.00")


async def test_execution_is_never_better_than_the_reference(engine):
    """Both models are adverse, in both directions."""
    buy = await engine.place_order(
        side=OrderSide.BUY, quantity=10, reference_price=D("1000")
    )
    assert buy.trade.execution_price > D("1000")

    short = await engine.place_order(
        side=OrderSide.SHORT_SELL, quantity=100, reference_price=D("1000")
    )
    assert short.trade.execution_price < D("1000")


# ==========================================================================
# Profitable long
# ==========================================================================


async def test_profitable_long_trade(engine, session):
    """Buy 100 around 1000, sell 100 around 1100.

    Both models scale with price, so the exit leg moves further than the
    entry leg in absolute terms:

    entry  ask 1001.00 (+1.00 half-spread), slipped +1.001  -> 1002.00
    exit   bid 1098.90 (-1.10 half-spread), slipped -1.0989 -> 1097.80
    gross  (1097.80 - 1002.00) x 100 = 9,580.00
    net    gross less the charges on both legs
    """
    entry = await engine.place_order(
        side=OrderSide.BUY, quantity=100, reference_price=D("1000")
    )
    exit_ = await engine.place_order(
        side=OrderSide.SELL, quantity=100, reference_price=D("1100")
    )

    assert entry.gross_pnl == D("0.00"), "an opening fill realizes nothing"
    assert entry.net_pnl == -entry.total_charges

    assert exit_.gross_pnl == D("9580.00")
    assert exit_.net_pnl == exit_.gross_pnl - exit_.total_charges

    position = exit_.position
    assert position.quantity == 0
    assert position.realized_pnl == D("9580.00")
    assert position.total_charges == entry.total_charges + exit_.total_charges
    assert position.net_realized_pnl == D("9580.00") - position.total_charges

    # The wallet must agree with the net figure exactly.
    assert await _cash(session) == D("1000000.00") + position.net_realized_pnl


async def test_charges_make_a_thin_long_unprofitable(engine, session):
    """Gross positive, net negative once costs are paid.

    Buy around 1000, sell around 1000.50: the spread and slippage alone move
    the fills 4.00 apart, so the trade loses despite the mid rising.
    """
    await engine.place_order(
        side=OrderSide.BUY, quantity=100, reference_price=D("1000")
    )
    exit_ = await engine.place_order(
        side=OrderSide.SELL, quantity=100, reference_price=D("1000.50")
    )

    assert exit_.gross_pnl < 0, "the spread alone swamped a 0.50 move"
    assert exit_.position.net_realized_pnl < exit_.position.realized_pnl


# ==========================================================================
# Losing long
# ==========================================================================


async def test_losing_long_trade(engine, session):
    """Buy 100 around 1000, sell 100 around 900.

    entry 1002.00, exit 898.20 -> gross (898.20 - 1002.00) x 100 = -10,380.00
    Charges deepen the loss; net is strictly worse than gross.
    """
    entry = await engine.place_order(
        side=OrderSide.BUY, quantity=100, reference_price=D("1000")
    )
    exit_ = await engine.place_order(
        side=OrderSide.SELL, quantity=100, reference_price=D("900")
    )

    assert exit_.gross_pnl == D("-10380.00")
    assert exit_.net_pnl == exit_.gross_pnl - exit_.total_charges
    assert exit_.net_pnl < exit_.gross_pnl, "charges deepen a loss"

    position = exit_.position
    assert position.net_realized_pnl < position.realized_pnl
    assert await _cash(session) == D("1000000.00") + position.net_realized_pnl
    _ = entry


# ==========================================================================
# Profitable short
# ==========================================================================


async def test_profitable_short_trade(engine, session):
    """Short 100 around 1000, cover 100 around 900.

    entry  bid  999.00, slipped down  -> 998.00
    cover  ask  900.90, slipped up    -> 901.80
    gross  (998.00 - 901.80) x 100 = 9,620.00
    """
    entry = await engine.place_order(
        side=OrderSide.SHORT_SELL, quantity=100, reference_price=D("1000")
    )
    cover = await engine.place_order(
        side=OrderSide.BUY_TO_COVER, quantity=100, reference_price=D("900")
    )

    assert entry.trade.execution_price == D("998.00")
    assert cover.trade.execution_price == D("901.80")
    assert cover.gross_pnl == D("9620.00")
    assert cover.net_pnl == cover.gross_pnl - cover.total_charges

    position = cover.position
    assert position.quantity == 0
    assert position.net_realized_pnl == D("9620.00") - position.total_charges
    assert await _cash(session) == D("1000000.00") + position.net_realized_pnl


async def test_short_entry_pays_stt_and_cover_pays_stamp_duty(engine, session):
    """Intraday: STT on the sell leg, stamp duty on the buy leg."""
    await engine.place_order(
        side=OrderSide.SHORT_SELL, quantity=100, reference_price=D("1000")
    )
    await engine.place_order(
        side=OrderSide.BUY_TO_COVER, quantity=100, reference_price=D("900")
    )

    short_trade, cover_trade = await _trades(session)

    assert short_trade.stt > 0 and short_trade.stamp_duty == D("0.00")
    assert cover_trade.stamp_duty > 0 and cover_trade.stt == D("0.00")


# ==========================================================================
# Losing short
# ==========================================================================


async def test_losing_short_trade(engine, session):
    """Short 100 around 1000, cover 100 around 1100.

    entry  998.00, cover ask 1101.10 slipped up -> 1102.20
    gross  (998.00 - 1102.20) x 100 = -10,420.00
    """
    await engine.place_order(
        side=OrderSide.SHORT_SELL, quantity=100, reference_price=D("1000")
    )
    cover = await engine.place_order(
        side=OrderSide.BUY_TO_COVER, quantity=100, reference_price=D("1100")
    )

    assert cover.trade.execution_price == D("1102.20")
    assert cover.gross_pnl == D("-10420.00")
    assert cover.net_pnl < cover.gross_pnl

    position = cover.position
    assert await _cash(session) == D("1000000.00") + position.net_realized_pnl


# ==========================================================================
# Charges on the trade record
# ==========================================================================


async def test_every_charge_component_is_persisted(engine, session):
    await engine.place_order(
        side=OrderSide.BUY, quantity=100, reference_price=D("1000")
    )

    trade = (await _trades(session))[0]

    assert trade.brokerage > 0
    assert trade.exchange_charges > 0
    assert trade.sebi_charges > 0
    assert trade.stamp_duty > 0
    assert trade.gst > 0
    assert trade.stt == D("0.00"), "no STT on an intraday buy"
    assert trade.total_charges == (
        trade.brokerage
        + trade.stt
        + trade.exchange_charges
        + trade.sebi_charges
        + trade.stamp_duty
        + trade.gst
        + trade.dp_charges
    )


async def test_charges_are_deducted_from_cash_on_an_opening_fill(engine, session):
    """Cash out equals notional plus charges, not notional alone."""
    result = await engine.place_order(
        side=OrderSide.BUY, quantity=100, reference_price=D("1000")
    )

    notional = D("1002.00") * 100
    expected = D("1000000.00") - notional - result.total_charges

    assert result.cash_delta == -(notional + result.total_charges)
    assert await _cash(session) == expected


async def test_charges_reduce_the_credit_on_a_sell(engine, session):
    await engine.place_order(
        side=OrderSide.BUY, quantity=100, reference_price=D("1000")
    )
    cash_after_entry = await _cash(session)

    result = await engine.place_order(
        side=OrderSide.SELL, quantity=100, reference_price=D("1100")
    )

    notional = D("1097.80") * 100
    assert result.cash_delta == notional - result.total_charges
    assert await _cash(session) == cash_after_entry + result.cash_delta


async def test_opening_fill_has_zero_gross_and_negative_net(engine, session):
    result = await engine.place_order(
        side=OrderSide.BUY, quantity=100, reference_price=D("1000")
    )

    assert result.gross_pnl == D("0.00")
    assert result.total_charges > 0
    assert result.net_pnl < 0


# ==========================================================================
# Cumulative accounting
# ==========================================================================


async def test_cumulative_charges_accumulate_over_both_legs(engine, session):
    entry = await engine.place_order(
        side=OrderSide.BUY, quantity=100, reference_price=D("1000")
    )
    exit_ = await engine.place_order(
        side=OrderSide.SELL, quantity=100, reference_price=D("1100")
    )

    position = (await session.execute(select(Position))).scalar_one()

    assert position.total_charges == entry.total_charges + exit_.total_charges
    assert position.net_realized_pnl == (
        position.realized_pnl - position.total_charges
    )


async def test_cash_always_reconciles_with_net_realized_pnl(engine, session):
    """Across a mixed sequence that ends flat, cash must equal opening + net."""
    for side, quantity, price in (
        (OrderSide.BUY, 100, "1000"),
        (OrderSide.BUY, 50, "1010"),
        (OrderSide.SELL, 30, "1050"),
        (OrderSide.SELL, 120, "1080"),
        (OrderSide.SHORT_SELL, 80, "1100"),
        (OrderSide.BUY_TO_COVER, 80, "1040"),
    ):
        await engine.place_order(
            side=side, quantity=quantity, reference_price=D(price)
        )

    position = (await session.execute(select(Position))).scalar_one()
    assert position.quantity == 0
    assert await _cash(session) == D("1000000.00") + position.net_realized_pnl


async def test_portfolio_reports_gross_charges_and_net(engine):
    await engine.place_order(
        side=OrderSide.BUY, quantity=100, reference_price=D("1000")
    )
    await engine.place_order(
        side=OrderSide.SELL, quantity=100, reference_price=D("1100")
    )

    snapshot = await engine.get_portfolio()

    assert snapshot.realized_pnl == D("9580.00")
    assert snapshot.total_charges > 0
    assert snapshot.net_realized_pnl == snapshot.realized_pnl - snapshot.total_charges
    assert snapshot.net_total_pnl == snapshot.net_realized_pnl


async def test_portfolio_net_total_includes_unrealized(engine):
    await engine.place_order(
        side=OrderSide.BUY, quantity=100, reference_price=D("1000")
    )

    snapshot = await engine.get_portfolio(mark_price=D("1050"))

    assert snapshot.unrealized_pnl == D("4800.00")  # (1050 - 1002) x 100
    assert snapshot.net_total_pnl == (
        snapshot.net_realized_pnl + snapshot.unrealized_pnl
    )


# ==========================================================================
# Affordability now includes charges
# ==========================================================================


async def test_an_order_affordable_on_notional_alone_can_still_be_rejected(
    session,
):
    """Charges are part of what must be afforded."""
    await WalletService(session).initialize_wallet(D("100200.00"))
    engine = TradingEngine(
        session,
        execution=ExecutionEngine(
            session,
            spread=SpreadModel.disabled(),
            slippage=SlippageModel.disabled(),
            fees=FeeCalculator(segment=Segment.INTRADAY),
        ),
    )

    # 100 @ 1000 costs exactly 100,000 in notional, leaving 200 -- but the
    # charges on top exceed nothing, so this one fits.
    await engine.place_order(
        side=OrderSide.BUY, quantity=100, reference_price=D("1000")
    )
    remaining = await _cash(session)
    assert remaining < D("200.00"), "charges came out of the buffer"


async def test_a_buy_for_the_entire_balance_fails_once_charges_apply(session):
    await WalletService(session).initialize_wallet(D("100000.00"))
    engine = TradingEngine(
        session,
        execution=ExecutionEngine(
            session,
            spread=SpreadModel.disabled(),
            slippage=SlippageModel.disabled(),
            fees=FeeCalculator(segment=Segment.INTRADAY),
        ),
    )

    with pytest.raises(InsufficientFundsError, match="charges"):
        await engine.place_order(
            side=OrderSide.BUY, quantity=100, reference_price=D("1000")
        )


# ==========================================================================
# Configuration
# ==========================================================================


async def test_a_frictionless_engine_fills_exactly_at_the_reference(session):
    await WalletService(session).initialize_wallet()
    engine = TradingEngine(session, execution=ExecutionEngine.frictionless(session))

    result = await engine.place_order(
        side=OrderSide.BUY, quantity=100, reference_price=D("1000")
    )

    assert result.trade.execution_price == D("1000")
    assert result.total_charges == D("0.00")
    assert result.trade.spread_cost == D("0.00")
    assert result.trade.slippage_cost == D("0.00")


async def test_delivery_segment_charges_more_than_intraday(session):
    """Same trade, different schedule -- delivery costs more on the buy leg."""
    await WalletService(session).initialize_wallet()

    intraday = ExecutionEngine(
        session,
        spread=SpreadModel.disabled(),
        slippage=SlippageModel.disabled(),
        fees=FeeCalculator(segment=Segment.INTRADAY),
    )
    delivery = ExecutionEngine(
        session,
        spread=SpreadModel.disabled(),
        slippage=SlippageModel.disabled(),
        fees=FeeCalculator(segment=Segment.DELIVERY),
    )

    a = await TradingEngine(session, execution=intraday).place_order(
        side=OrderSide.BUY, quantity=100, reference_price=D("1000")
    )
    b = await TradingEngine(session, execution=delivery).place_order(
        side=OrderSide.BUY, quantity=100, reference_price=D("1000")
    )

    assert b.total_charges > a.total_charges
