"""Cryptocurrency trading tests.

Covers what the crypto asset class adds on top of the existing engine:

* the four sides working on a coin, exactly as they do on a share;
* **fractional** quantities, end to end and exactly (no float drift);
* the whole-unit rule still holding for equities;
* a stop-loss firing on a crypto long and on a crypto short;
* charges being asset-aware -- no STT or stamp duty on a coin, no TDS on a
  share;
* a multi-asset portfolio valued as one account;
* persistence of a fractional position across a "restart".

The engine is exercised directly. There is no separate crypto execution path
to test: a coin goes through the same ``TradingEngine.place_order`` a share
does, which is the property these tests are here to protect.
"""

from decimal import Decimal

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.automation.monitor import (
    AutomaticOrderMonitor,
    reset_automatic_order_monitor,
)
from app.automation.service import AutomaticOrderService
from app.core.exceptions import (
    InvalidQuantityError,
    MarketClosedError,
    UnsupportedSymbolError,
)
from app.db.session import SessionLocal
from app.market_data.instruments import (
    AssetClass,
    normalise_quantity,
    resolve_instrument,
)
from app.models.automatic_order import (
    AutomaticOrderStatus,
    AutomaticOrderType,
    TriggerCondition,
)
from app.models.enums import OrderSide
from app.models.trading import Position, Trade
from app.models.wallet import Wallet
from app.trading.engine import TradingEngine
from app.trading.execution import ExecutionEngine
from app.trading.fees import CryptoFeeCalculator, FeeCalculator, fee_calculator_for

D = Decimal

BTC = "BTC"
ETH = "ETH"
STOCK = "RELIANCE"

#: Order-of-magnitude realistic INR prices, so the arithmetic reads sensibly.
BTC_PRICE = D("7600000.00")
ETH_PRICE = D("240000.00")
STOCK_PRICE = D("1400.00")


@pytest.fixture
async def wallet(session: AsyncSession) -> Wallet:
    """A funded account. Large enough to buy a meaningful slice of a Bitcoin."""
    row = Wallet(
        initial_balance=D("10000000.00"),
        cash_balance=D("10000000.00"),
        currency="INR",
    )
    session.add(row)
    await session.commit()
    await session.refresh(row)
    return row


@pytest.fixture
def engine(session: AsyncSession) -> TradingEngine:
    """Frictionless, so position arithmetic is visible without fee noise."""
    return TradingEngine(session, execution=ExecutionEngine.frictionless(session))


@pytest.fixture
def costed_engine(session: AsyncSession) -> TradingEngine:
    """The real cost models, for the charge tests."""
    return TradingEngine(session)


# ==========================================================================
# The instrument catalogue
# ==========================================================================


def test_bitcoin_and_ethereum_are_in_the_universe():
    for symbol, name in ((BTC, "Bitcoin"), (ETH, "Ethereum")):
        instrument = resolve_instrument(symbol)
        assert instrument.asset_class is AssetClass.CRYPTO
        assert instrument.company_name == name


def test_a_coin_is_fractional_and_a_share_is_not():
    assert resolve_instrument(BTC).is_fractional is True
    assert resolve_instrument(BTC).quantity_step == D("0.00000001")
    assert resolve_instrument(STOCK).is_fractional is False
    assert resolve_instrument(STOCK).quantity_step == D("1")


def test_a_coin_carries_its_own_exchange_code_and_trading_hours():
    instrument = resolve_instrument(BTC)
    assert instrument.exchange == "CRYPTO"
    assert instrument.trading_hours == "24/7"


def test_an_unknown_coin_is_still_rejected():
    with pytest.raises(UnsupportedSymbolError):
        resolve_instrument("NOTACOIN")


# ==========================================================================
# Quantity rules
# ==========================================================================


def test_a_share_rejects_a_fractional_quantity():
    with pytest.raises(InvalidQuantityError, match="whole units"):
        normalise_quantity(resolve_instrument(STOCK), "0.5")


def test_a_coin_accepts_a_fractional_quantity():
    assert normalise_quantity(resolve_instrument(BTC), "0.001") == D("0.001")


def test_a_coin_rejects_a_size_finer_than_one_satoshi():
    with pytest.raises(InvalidQuantityError, match="increments of"):
        normalise_quantity(resolve_instrument(BTC), "0.000000001")


def test_exactly_one_satoshi_is_a_legal_size():
    assert normalise_quantity(resolve_instrument(BTC), "0.00000001") == D("0.00000001")


@pytest.mark.parametrize("bad", ["0", "-1", "-0.001"])
def test_a_non_positive_quantity_is_rejected_for_every_asset_class(bad):
    for symbol in (STOCK, BTC):
        with pytest.raises(InvalidQuantityError):
            normalise_quantity(resolve_instrument(symbol), bad)


def test_a_float_quantity_does_not_leak_binary_noise_into_the_ledger():
    """0.1 as a float is 0.1000000000000000055...; via str it is exactly 0.1."""
    assert normalise_quantity(resolve_instrument(BTC), 0.1) == D("0.1")


# ==========================================================================
# BUY / SELL / SHORT / COVER on a coin
# ==========================================================================


async def test_buying_bitcoin_opens_a_fractional_long(engine, wallet):
    result = await engine.place_order(
        side=OrderSide.BUY,
        quantity="0.01",
        reference_price=BTC_PRICE,
        symbol=BTC,
    )
    assert result.position.quantity == D("0.01")
    assert result.position.symbol == BTC
    assert result.position.asset_class is AssetClass.CRYPTO
    assert result.order.exchange == "CRYPTO"


async def test_buying_bitcoin_debits_exactly_the_notional(engine, wallet, session):
    await engine.place_order(
        side=OrderSide.BUY,
        quantity="0.01",
        reference_price=BTC_PRICE,
        symbol=BTC,
    )
    await session.refresh(wallet)
    # 0.01 x 7,600,000 = 76,000 exactly. No float would land on this.
    assert wallet.cash_balance == D("10000000.00") - D("76000.00")


async def test_selling_bitcoin_closes_the_long_and_realizes_the_gain(engine, wallet):
    await engine.place_order(
        side=OrderSide.BUY, quantity="0.01", reference_price=BTC_PRICE, symbol=BTC
    )
    result = await engine.place_order(
        side=OrderSide.SELL,
        quantity="0.01",
        reference_price=D("7700000.00"),
        symbol=BTC,
    )
    assert result.position.quantity == 0
    # 0.01 x (7,700,000 - 7,600,000) = 1,000
    assert result.gross_pnl == D("1000.00")


async def test_shorting_bitcoin_opens_a_fractional_short(engine, wallet):
    result = await engine.place_order(
        side=OrderSide.SHORT_SELL,
        quantity="0.005",
        reference_price=BTC_PRICE,
        symbol=BTC,
    )
    assert result.position.quantity == D("-0.005")


async def test_covering_bitcoin_closes_the_short_and_realizes_the_gain(engine, wallet):
    await engine.place_order(
        side=OrderSide.SHORT_SELL,
        quantity="0.005",
        reference_price=BTC_PRICE,
        symbol=BTC,
    )
    result = await engine.place_order(
        side=OrderSide.BUY_TO_COVER,
        quantity="0.005",
        reference_price=D("7500000.00"),
        symbol=BTC,
    )
    assert result.position.quantity == 0
    # A short profits when the price falls: 0.005 x 100,000 = 500
    assert result.gross_pnl == D("500.00")


async def test_a_fractional_quantity_survives_the_database_exactly(engine, wallet, session):
    await engine.place_order(
        side=OrderSide.BUY,
        quantity="0.00000001",
        reference_price=BTC_PRICE,
        symbol=BTC,
    )
    session.expunge_all()
    position = (
        await session.execute(select(Position).where(Position.symbol == BTC))
    ).scalar_one()
    assert position.quantity == D("0.00000001")


async def test_buying_ethereum_works_the_same_way(engine, wallet):
    result = await engine.place_order(
        side=OrderSide.BUY, quantity="0.05", reference_price=ETH_PRICE, symbol=ETH
    )
    assert result.position.quantity == D("0.05")
    assert result.position.symbol == ETH


async def test_adding_to_a_fractional_long_reaverages_correctly(engine, wallet):
    await engine.place_order(
        side=OrderSide.BUY, quantity="0.01", reference_price=D("7000000"), symbol=BTC
    )
    result = await engine.place_order(
        side=OrderSide.BUY, quantity="0.01", reference_price=D("8000000"), symbol=BTC
    )
    assert result.position.quantity == D("0.02")
    assert result.position.average_price == D("7500000.0000")


async def test_selling_more_bitcoin_than_held_is_still_rejected(engine, wallet):
    from app.core.exceptions import InvalidPositionOperationError

    await engine.place_order(
        side=OrderSide.BUY, quantity="0.01", reference_price=BTC_PRICE, symbol=BTC
    )
    with pytest.raises(InvalidPositionOperationError):
        await engine.place_order(
            side=OrderSide.SELL,
            quantity="0.02",
            reference_price=BTC_PRICE,
            symbol=BTC,
        )


async def test_a_fractional_order_on_an_equity_is_rejected_by_the_engine(engine, wallet):
    with pytest.raises(InvalidQuantityError):
        await engine.place_order(
            side=OrderSide.BUY,
            quantity="0.5",
            reference_price=STOCK_PRICE,
            symbol=STOCK,
        )


# ==========================================================================
# Charges are asset-aware
# ==========================================================================


def test_the_fee_router_returns_a_different_schedule_per_asset_class():
    assert isinstance(fee_calculator_for(AssetClass.STOCK), FeeCalculator)
    assert isinstance(fee_calculator_for(AssetClass.CRYPTO), CryptoFeeCalculator)


def test_a_crypto_sell_is_charged_no_stt_stamp_duty_sebi_fee_or_dp_charge():
    charges = CryptoFeeCalculator().calculate(
        side=OrderSide.SELL, quantity=D("0.01"), price=BTC_PRICE
    )
    # Every one of these is a securities-market charge with no crypto analogue.
    assert charges.stt == 0
    assert charges.stamp_duty == 0
    assert charges.sebi_charges == 0
    assert charges.exchange_charges == 0
    assert charges.dp_charges == 0


def test_a_crypto_trade_is_charged_the_configured_exchange_fee():
    charges = CryptoFeeCalculator(fee_percent=D("0.10"), tds_percent=D("0")).calculate(
        side=OrderSide.BUY, quantity=D("0.01"), price=BTC_PRICE
    )
    # 0.10% of 76,000 turnover.
    assert charges.brokerage == D("76.00")
    # GST is charged on the fee, not on the turnover.
    assert charges.gst == D("13.68")


def test_tds_is_withheld_on_a_crypto_sell_and_not_on_a_buy():
    calculator = CryptoFeeCalculator(tds_percent=D("1"))
    buy = calculator.calculate(side=OrderSide.BUY, quantity=D("0.01"), price=BTC_PRICE)
    sell = calculator.calculate(
        side=OrderSide.SELL, quantity=D("0.01"), price=BTC_PRICE
    )
    assert buy.tds == 0
    # 1% of the 76,000 disposal.
    assert sell.tds == D("760.00")


def test_an_equity_trade_is_never_charged_tds():
    charges = FeeCalculator().calculate(
        side=OrderSide.SELL, quantity=D("100"), price=STOCK_PRICE
    )
    assert charges.tds == 0


def test_charges_scale_with_a_fractional_quantity():
    calculator = CryptoFeeCalculator(fee_percent=D("0.10"), tds_percent=D("0"))
    tenth = calculator.calculate(
        side=OrderSide.BUY, quantity=D("0.001"), price=BTC_PRICE
    )
    whole = calculator.calculate(
        side=OrderSide.BUY, quantity=D("0.01"), price=BTC_PRICE
    )
    assert tenth.brokerage * 10 == whole.brokerage


async def test_a_live_crypto_fill_records_the_crypto_schedule(costed_engine, wallet, session):
    await costed_engine.place_order(
        side=OrderSide.BUY, quantity="0.01", reference_price=BTC_PRICE, symbol=BTC
    )
    trade = (
        await session.execute(select(Trade).where(Trade.symbol == BTC))
    ).scalar_one()

    assert trade.asset_class is AssetClass.CRYPTO
    assert trade.stt == 0 and trade.stamp_duty == 0
    assert trade.brokerage > 0


async def test_a_live_equity_fill_still_records_the_equity_schedule(
    costed_engine, wallet, session
):
    await costed_engine.place_order(
        side=OrderSide.BUY,
        quantity=100,
        reference_price=STOCK_PRICE,
        symbol=STOCK,
    )
    trade = (
        await session.execute(select(Trade).where(Trade.symbol == STOCK))
    ).scalar_one()

    assert trade.asset_class is AssetClass.STOCK
    assert trade.tds == 0
    # Stamp duty is charged on an equity buy and is the marker that the NSE
    # schedule ran.
    assert trade.stamp_duty > 0


# ==========================================================================
# Market hours
# ==========================================================================


async def test_crypto_can_be_traded_even_with_market_hours_enforced(
    engine, wallet, monkeypatch
):
    """The requirement in one test: enforcement on, coin still tradable."""
    from app.core.config import settings

    monkeypatch.setattr(settings, "ENFORCE_MARKET_HOURS", True)

    result = await engine.place_order(
        side=OrderSide.BUY, quantity="0.001", reference_price=BTC_PRICE, symbol=BTC
    )
    assert result.position.quantity == D("0.001")


async def test_an_equity_is_refused_out_of_hours_when_enforcement_is_on(
    engine, wallet, monkeypatch
):
    from app.core.config import settings
    from app.markets import registry as calendar_registry

    monkeypatch.setattr(settings, "ENFORCE_MARKET_HOURS", True)

    class _Shut:
        name = "test"

        def trading_status(self, at=None):
            from app.markets.calendar import MarketSession, TradingStatus
            from datetime import UTC, datetime

            return MarketSession(
                status=TradingStatus.CLOSED,
                is_open=False,
                at=datetime.now(tz=UTC),
                timezone="Asia/Kolkata",
                next_open=None,
                next_close=None,
                reason="NSE has closed for the day.",
            )

    monkeypatch.setattr(
        calendar_registry, "calendar_for", lambda instrument: _Shut()
    )
    monkeypatch.setattr(
        "app.trading.engine.calendar_for", lambda instrument: _Shut()
    )

    with pytest.raises(MarketClosedError):
        await engine.place_order(
            side=OrderSide.BUY,
            quantity=10,
            reference_price=STOCK_PRICE,
            symbol=STOCK,
        )


async def test_an_equity_is_accepted_out_of_hours_by_default(engine, wallet):
    """ENFORCE_MARKET_HOURS is off by default, preserving existing behaviour."""
    from app.core.config import settings

    assert settings.ENFORCE_MARKET_HOURS is False
    result = await engine.place_order(
        side=OrderSide.BUY, quantity=10, reference_price=STOCK_PRICE, symbol=STOCK
    )
    assert result.position.quantity == 10


# ==========================================================================
# Stop-loss on crypto
# ==========================================================================


@pytest.fixture(autouse=True)
def _fresh_monitor():
    reset_automatic_order_monitor()
    yield
    reset_automatic_order_monitor()


async def test_a_stop_loss_on_a_crypto_long_fires_a_sell(engine, wallet, session):
    await engine.place_order(
        side=OrderSide.BUY, quantity="0.01", reference_price=BTC_PRICE, symbol=BTC
    )
    await AutomaticOrderService(session).create(
        order_type=AutomaticOrderType.STOP_LOSS,
        trigger_price=D("7200000.00"),
        trigger_condition=TriggerCondition.LTE,
        action=OrderSide.SELL,
        quantity="0.01",
        symbol=BTC,
        reference_price=BTC_PRICE,
    )

    monitor = AutomaticOrderMonitor(session_factory=SessionLocal)
    events = await monitor.on_price(market_price=D("7150000.00"), symbol=BTC)

    assert len(events) == 1
    assert events[0]["data"]["event"] == "triggered"
    assert events[0]["data"]["action"] == "SELL"

    async with SessionLocal() as check:
        position = (
            await check.execute(select(Position).where(Position.symbol == BTC))
        ).scalar_one()
        assert position.quantity == 0


async def test_a_stop_loss_on_a_crypto_short_fires_a_cover(engine, wallet, session):
    await engine.place_order(
        side=OrderSide.SHORT_SELL,
        quantity="0.01",
        reference_price=BTC_PRICE,
        symbol=BTC,
    )
    await AutomaticOrderService(session).create(
        order_type=AutomaticOrderType.STOP_LOSS,
        trigger_price=D("8000000.00"),
        trigger_condition=TriggerCondition.GTE,
        action=OrderSide.BUY_TO_COVER,
        quantity="0.01",
        symbol=BTC,
        reference_price=BTC_PRICE,
    )

    monitor = AutomaticOrderMonitor(session_factory=SessionLocal)
    events = await monitor.on_price(market_price=D("8100000.00"), symbol=BTC)

    assert len(events) == 1
    assert events[0]["data"]["action"] == "BUY_TO_COVER"

    async with SessionLocal() as check:
        position = (
            await check.execute(select(Position).where(Position.symbol == BTC))
        ).scalar_one()
        assert position.quantity == 0


async def test_a_crypto_stop_loss_may_protect_a_fractional_quantity(
    engine, wallet, session
):
    await engine.place_order(
        side=OrderSide.BUY, quantity="0.001", reference_price=BTC_PRICE, symbol=BTC
    )
    order = await AutomaticOrderService(session).create(
        order_type=AutomaticOrderType.STOP_LOSS,
        trigger_price=D("7000000.00"),
        trigger_condition=TriggerCondition.LTE,
        action=OrderSide.SELL,
        quantity="0.001",
        symbol=BTC,
        reference_price=BTC_PRICE,
    )
    assert order.quantity == D("0.001")
    assert order.asset_class is AssetClass.CRYPTO


async def test_a_crypto_trigger_does_not_fire_on_another_symbols_price(
    engine, wallet, session
):
    await engine.place_order(
        side=OrderSide.BUY, quantity="0.01", reference_price=BTC_PRICE, symbol=BTC
    )
    await AutomaticOrderService(session).create(
        order_type=AutomaticOrderType.STOP_LOSS,
        trigger_price=D("7200000.00"),
        trigger_condition=TriggerCondition.LTE,
        action=OrderSide.SELL,
        quantity="0.01",
        symbol=BTC,
        reference_price=BTC_PRICE,
    )

    monitor = AutomaticOrderMonitor(session_factory=SessionLocal)
    # Ethereum's price is far below BTC's trigger, but belongs to another
    # instrument entirely.
    events = await monitor.on_price(market_price=D("240000.00"), symbol=ETH)
    assert events == []


async def test_the_monitor_reports_which_symbols_are_armed(engine, wallet, session):
    """The stream reads this to keep polling with no browser connected."""
    await engine.place_order(
        side=OrderSide.BUY, quantity="0.01", reference_price=BTC_PRICE, symbol=BTC
    )
    await AutomaticOrderService(session).create(
        order_type=AutomaticOrderType.STOP_LOSS,
        trigger_price=D("7200000.00"),
        trigger_condition=TriggerCondition.LTE,
        action=OrderSide.SELL,
        quantity="0.01",
        symbol=BTC,
        reference_price=BTC_PRICE,
    )

    monitor = AutomaticOrderMonitor(session_factory=SessionLocal)
    assert await monitor.refresh_armed_symbols() == frozenset({BTC})


# ==========================================================================
# Multi-asset portfolio
# ==========================================================================


async def test_a_stock_and_a_coin_are_held_side_by_side(engine, wallet):
    await engine.place_order(
        side=OrderSide.BUY, quantity=100, reference_price=STOCK_PRICE, symbol=STOCK
    )
    await engine.place_order(
        side=OrderSide.BUY, quantity="0.01", reference_price=BTC_PRICE, symbol=BTC
    )
    await engine.place_order(
        side=OrderSide.SHORT_SELL, quantity="0.5", reference_price=ETH_PRICE, symbol=ETH
    )

    positions = {p.symbol: p for p in await engine.list_positions()}
    assert positions[STOCK].quantity == 100
    assert positions[BTC].quantity == D("0.01")
    assert positions[ETH].quantity == D("-0.5")


async def test_the_portfolio_totals_stocks_and_crypto_into_one_account(engine, wallet):
    await engine.place_order(
        side=OrderSide.BUY, quantity=100, reference_price=STOCK_PRICE, symbol=STOCK
    )
    await engine.place_order(
        side=OrderSide.BUY, quantity="0.01", reference_price=BTC_PRICE, symbol=BTC
    )

    summary = await engine.get_portfolio_summary(
        mark_prices={STOCK: STOCK_PRICE, BTC: BTC_PRICE}
    )
    # 100 x 1,400 = 140,000 and 0.01 x 7,600,000 = 76,000.
    assert summary.position_value == D("216000.00")
    # One wallet funds both: 10,000,000 - 140,000 - 76,000.
    assert summary.cash_balance == D("9784000.00")
    assert summary.total_equity == D("10000000.00")


async def test_the_portfolio_splits_value_by_asset_class(engine, wallet):
    await engine.place_order(
        side=OrderSide.BUY, quantity=100, reference_price=STOCK_PRICE, symbol=STOCK
    )
    await engine.place_order(
        side=OrderSide.BUY, quantity="0.01", reference_price=BTC_PRICE, symbol=BTC
    )

    summary = await engine.get_portfolio_summary(
        mark_prices={STOCK: STOCK_PRICE, BTC: BTC_PRICE}
    )
    split = summary.value_by_asset_class()
    assert split[AssetClass.STOCK] == D("140000.00")
    assert split[AssetClass.CRYPTO] == D("76000.00")


async def test_an_unpriced_coin_is_reported_rather_than_guessed_at(engine, wallet):
    await engine.place_order(
        side=OrderSide.BUY, quantity="0.01", reference_price=BTC_PRICE, symbol=BTC
    )
    summary = await engine.get_portfolio_summary(mark_prices={})
    assert summary.unpriced_symbols == [BTC]
    assert summary.position_value == 0


async def test_unrealized_pnl_is_exact_on_a_fractional_position(engine, wallet):
    await engine.place_order(
        side=OrderSide.BUY, quantity="0.001", reference_price=BTC_PRICE, symbol=BTC
    )
    summary = await engine.get_portfolio_summary(
        mark_prices={BTC: D("7700000.00")}
    )
    # 0.001 x 100,000 = 100 exactly.
    assert summary.unrealized_pnl == D("100.00")


# ==========================================================================
# Persistence
# ==========================================================================


async def test_a_fractional_crypto_position_survives_a_restart(engine, wallet):
    """A new session with a fresh identity map -- the ledger, not the cache."""
    await engine.place_order(
        side=OrderSide.BUY, quantity="0.00123456", reference_price=BTC_PRICE, symbol=BTC
    )

    async with SessionLocal() as restarted:
        position = await TradingEngine(restarted).get_position(BTC)
        assert position.quantity == D("0.00123456")
        assert position.asset_class is AssetClass.CRYPTO

        trades = await TradingEngine(restarted).list_trades()
        assert any(t.symbol == BTC and t.quantity == D("0.00123456") for t in trades)


async def test_a_crypto_trigger_survives_a_restart(engine, wallet, session):
    await engine.place_order(
        side=OrderSide.BUY, quantity="0.01", reference_price=BTC_PRICE, symbol=BTC
    )
    created = await AutomaticOrderService(session).create(
        order_type=AutomaticOrderType.STOP_LOSS,
        trigger_price=D("7000000.00"),
        trigger_condition=TriggerCondition.LTE,
        action=OrderSide.SELL,
        quantity="0.01",
        symbol=BTC,
        reference_price=BTC_PRICE,
    )

    async with SessionLocal() as restarted:
        order = await AutomaticOrderService(restarted).get(created.id)
        assert order.status is AutomaticOrderStatus.ACTIVE
        assert order.quantity == D("0.01")
        assert order.symbol == BTC


# ==========================================================================
# Backtesting a coin
# ==========================================================================


def _candles(count: int, start_price: Decimal, step: Decimal):
    """An oscillating series with CONTINUOUS hourly bars, weekends included.

    Deliberately hourly and unbroken: an NSE series would have gaps at every
    close and every weekend. If anything in the engine assumed a session
    calendar, this series would expose it.

    The zigzag matters too -- a moving-average crossover only signals when the
    averages actually cross, so a monotone ramp would produce no trades and
    the test would prove nothing about sizing.
    """
    import math
    from datetime import UTC, datetime, timedelta

    from app.schemas.market_data import Candle

    begin = datetime(2026, 8, 28, 0, 0, tzinfo=UTC)  # a Friday
    bars = []
    for index in range(count):
        # Roughly three full cycles across the series, so the fast and slow
        # averages cross several times.
        swing = Decimal(str(round(math.sin(index / 6.0), 6)))
        price = start_price + step * swing * 20
        bars.append(
            Candle(
                timestamp=begin + timedelta(hours=index),
                open=price,
                high=price * D("1.01"),
                low=price * D("0.99"),
                close=price,
                volume=1000,
            )
        )
    return bars


def test_percent_of_equity_sizing_on_bitcoin_is_a_real_fraction_not_zero():
    """The defect this fixes: int(950000 / 7600000) == 0, so nothing traded."""
    from app.backtest.engine import BacktestConfig, PositionSizer, SizingMode

    sizer = PositionSizer(
        BacktestConfig(sizing_mode=SizingMode.PERCENT_OF_EQUITY, equity_percent=D("95")),
        resolve_instrument(BTC),
    )
    size = sizer.target_size(equity=D("1000000"), price=BTC_PRICE)

    assert size > 0
    # 950,000 / 7,600,000 = 0.125
    assert size == D("0.125")


def test_percent_of_equity_sizing_on_a_share_still_returns_whole_shares():
    from app.backtest.engine import BacktestConfig, PositionSizer, SizingMode

    sizer = PositionSizer(
        BacktestConfig(sizing_mode=SizingMode.PERCENT_OF_EQUITY, equity_percent=D("95")),
        resolve_instrument(STOCK),
    )
    size = sizer.target_size(equity=D("1000000"), price=STOCK_PRICE)

    # 950,000 / 1,400 = 678.57 -> 678 whole shares, rounded DOWN.
    assert size == D("678")
    assert size % 1 == 0


def test_crypto_sizing_rounds_down_to_a_whole_number_of_satoshis():
    from app.backtest.engine import BacktestConfig, PositionSizer, SizingMode

    sizer = PositionSizer(
        BacktestConfig(sizing_mode=SizingMode.FIXED_VALUE, fixed_value=D("1000")),
        resolve_instrument(BTC),
    )
    size = sizer.target_size(equity=D("1000000"), price=D("7777777"))

    assert size % D("0.00000001") == 0
    # Rounded down, so the order never exceeds the budget.
    assert size * D("7777777") <= D("1000")


def test_a_crypto_backtest_runs_over_a_continuous_series_and_trades():
    from app.backtest.engine import BacktestConfig, BacktestEngine, SizingMode
    from app.strategies.ma_crossover import MovingAverageCrossover

    engine = BacktestEngine(
        config=BacktestConfig(
            initial_capital=D("1000000.00"),
            sizing_mode=SizingMode.PERCENT_OF_EQUITY,
        )
    )
    result = engine.run(
        strategy=MovingAverageCrossover(fast=3, slow=8),
        candles=_candles(120, D("7000000"), D("10000")),
        symbol=BTC,
        interval="1h",
    )

    assert result.symbol == BTC
    assert result.asset_class == "CRYPTO"
    assert result.trading_calendar == "crypto"
    assert result.bars == 120
    # The point of the sizing fix: a BTC run actually takes a position.
    assert result.total_trades > 0


def test_a_crypto_backtest_keeps_weekend_bars_rather_than_dropping_them():
    """A 24/7 series legitimately contains Saturday and Sunday bars."""
    from app.backtest.engine import BacktestEngine
    from app.strategies.ma_crossover import MovingAverageCrossover

    candles = _candles(120, D("7000000"), D("10000"))
    result = BacktestEngine().run(
        strategy=MovingAverageCrossover(fast=3, slow=8),
        candles=candles,
        symbol=BTC,
        interval="1h",
    )

    weekdays = {point.timestamp.weekday() for point in result.equity_curve}
    assert {5, 6} <= weekdays, "weekend bars must survive into the equity curve"
    assert result.bars == len(candles)


def test_an_nse_backtest_still_reports_the_nse_calendar():
    from app.backtest.engine import BacktestEngine
    from app.strategies.ma_crossover import MovingAverageCrossover

    result = BacktestEngine().run(
        strategy=MovingAverageCrossover(fast=3, slow=8),
        candles=_candles(60, D("1400"), D("5")),
        symbol=STOCK,
        interval="1d",
    )

    assert result.asset_class == "STOCK"
    assert result.trading_calendar == "nse"
    # Whole shares only, even though the ledger column is fractional.
    assert all(trade.quantity % 1 == 0 for trade in result.trades)


def test_a_crypto_backtest_charges_the_crypto_schedule():
    """No STT on a coin, even in a backtest."""
    from app.backtest.engine import BacktestConfig, BacktestEngine, SizingMode
    from app.strategies.ma_crossover import MovingAverageCrossover

    engine = BacktestEngine(
        config=BacktestConfig(sizing_mode=SizingMode.PERCENT_OF_EQUITY)
    )
    result = engine.run(
        strategy=MovingAverageCrossover(fast=3, slow=8),
        candles=_candles(120, D("7000000"), D("10000")),
        symbol=BTC,
        interval="1h",
    )

    assert result.total_trades > 0
    # Charges are levied (a fee and TDS exist), but via the crypto schedule.
    assert result.total_charges > 0
