"""Trading engine tests against a real PostgreSQL database.

These cover what the pure accounting tests cannot: cash movement, persistence,
transaction atomicity and the constraints the database itself enforces.

They run on a **frictionless** engine -- no spread, no slippage, no charges --
so that position accounting is verified in isolation. Execution costs have
their own suites in ``test_execution_costs.py`` and
``test_realistic_execution.py``.
"""

from decimal import Decimal

import pytest
from sqlalchemy import func, select

from app.core.exceptions import (
    InsufficientFundsError,
    InvalidOrderError,
    InvalidPositionOperationError,
    UnsupportedSymbolError,
    WalletNotFoundError,
)
from app.models.enums import OrderSide, OrderStatus
from app.models.trading import Order, Position, Trade
from app.models.wallet import Wallet
from app.services.wallet_service import WalletService
from app.trading.engine import TradingEngine
from app.trading.execution import ExecutionEngine

D = Decimal


@pytest.fixture
async def engine(session) -> TradingEngine:
    """A frictionless engine with a funded wallet (INR 10,00,000).

    Fills land exactly on the reference price, so the numbers below isolate
    position accounting from execution costs.
    """
    await WalletService(session).initialize_wallet()
    return TradingEngine(session, execution=ExecutionEngine.frictionless(session))


@pytest.fixture
async def unfunded_engine(session) -> TradingEngine:
    """A trading engine whose wallet has never been initialised."""
    return TradingEngine(session, execution=ExecutionEngine.frictionless(session))


async def _cash(session) -> Decimal:
    wallet = (await session.execute(select(Wallet))).scalar_one()
    await session.refresh(wallet)
    return wallet.cash_balance


# --------------------------------------------------------------------------
# Long entry and exit
# --------------------------------------------------------------------------


async def test_long_entry_moves_position_and_debits_cash(engine, session):
    """BUY 100 @ 1400 -> +100, cash down 140,000."""
    result = await engine.place_order(
        side=OrderSide.BUY, quantity=100, reference_price=D("1400")
    )

    assert result.position.quantity == 100
    assert result.position.average_price == D("1400.0000")
    assert result.gross_pnl == D("0.00")
    assert result.cash_delta == D("-140000.00")
    assert await _cash(session) == D("860000.00")


async def test_long_exit_credits_cash_and_realizes_profit(engine, session):
    """BUY 100 @ 1400 then SELL 100 @ 1450 -> flat, +5,000, cash 1,005,000."""
    await engine.place_order(
        side=OrderSide.BUY, quantity=100, reference_price=D("1400")
    )

    result = await engine.place_order(
        side=OrderSide.SELL, quantity=100, reference_price=D("1450")
    )

    assert result.position.quantity == 0
    assert result.position.average_price == D("0.0000")
    assert result.gross_pnl == D("5000.00")
    assert result.position.realized_pnl == D("5000.00")
    assert await _cash(session) == D("1005000.00")


async def test_partial_long_exit(engine, session):
    """BUY 100 @ 1400, SELL 40 @ 1450 -> +60 @ 1400, +2,000 realized."""
    await engine.place_order(
        side=OrderSide.BUY, quantity=100, reference_price=D("1400")
    )

    result = await engine.place_order(
        side=OrderSide.SELL, quantity=40, reference_price=D("1450")
    )

    assert result.position.quantity == 60
    assert result.position.average_price == D("1400.0000")
    assert result.gross_pnl == D("2000.00")
    # -140,000 then +58,000
    assert await _cash(session) == D("918000.00")


async def test_long_exit_at_a_loss(engine, session):
    await engine.place_order(
        side=OrderSide.BUY, quantity=100, reference_price=D("1400")
    )

    result = await engine.place_order(
        side=OrderSide.SELL, quantity=100, reference_price=D("1350")
    )

    assert result.gross_pnl == D("-5000.00")
    assert await _cash(session) == D("995000.00")


# --------------------------------------------------------------------------
# Short entry and cover
# --------------------------------------------------------------------------


async def test_short_entry_credits_proceeds(engine, session):
    """SHORT 100 @ 1450 -> -100, cash up 145,000."""
    result = await engine.place_order(
        side=OrderSide.SHORT_SELL, quantity=100, reference_price=D("1450")
    )

    assert result.position.quantity == -100
    assert result.position.average_price == D("1450.0000")
    assert result.gross_pnl == D("0.00")
    assert await _cash(session) == D("1145000.00")


async def test_short_cover_realizes_profit(engine, session):
    """SHORT 100 @ 1450 then BUY_TO_COVER 100 @ 1400 -> flat, +5,000."""
    await engine.place_order(
        side=OrderSide.SHORT_SELL, quantity=100, reference_price=D("1450")
    )

    result = await engine.place_order(
        side=OrderSide.BUY_TO_COVER, quantity=100, reference_price=D("1400")
    )

    assert result.position.quantity == 0
    assert result.gross_pnl == D("5000.00")
    assert await _cash(session) == D("1005000.00")


async def test_short_cover_at_a_loss(engine, session):
    await engine.place_order(
        side=OrderSide.SHORT_SELL, quantity=100, reference_price=D("1450")
    )

    result = await engine.place_order(
        side=OrderSide.BUY_TO_COVER, quantity=100, reference_price=D("1500")
    )

    assert result.gross_pnl == D("-5000.00")
    assert await _cash(session) == D("995000.00")


async def test_partial_short_cover(engine):
    await engine.place_order(
        side=OrderSide.SHORT_SELL, quantity=100, reference_price=D("1450")
    )

    result = await engine.place_order(
        side=OrderSide.BUY_TO_COVER, quantity=30, reference_price=D("1400")
    )

    assert result.position.quantity == -70
    assert result.position.average_price == D("1450.0000")
    assert result.gross_pnl == D("1500.00")


async def test_plain_buy_also_covers_a_short(engine):
    """The specification's example uses BUY, not BUY_TO_COVER, to close."""
    await engine.place_order(
        side=OrderSide.SHORT_SELL, quantity=100, reference_price=D("1450")
    )

    result = await engine.place_order(
        side=OrderSide.BUY, quantity=100, reference_price=D("1400")
    )

    assert result.position.quantity == 0
    assert result.gross_pnl == D("5000.00")


# --------------------------------------------------------------------------
# Reversals
# --------------------------------------------------------------------------


async def test_reversal_from_long_to_short(engine, session):
    """+100 @ 1400, then SHORT_SELL 150 @ 1450 -> -50 @ 1450, +5,000."""
    await engine.place_order(
        side=OrderSide.BUY, quantity=100, reference_price=D("1400")
    )

    result = await engine.place_order(
        side=OrderSide.SHORT_SELL, quantity=150, reference_price=D("1450")
    )

    assert result.position.quantity == -50
    assert result.position.average_price == D("1450.0000")
    assert result.gross_pnl == D("5000.00")
    # -140,000 then +217,500
    assert await _cash(session) == D("1077500.00")


async def test_reversal_from_short_to_long(engine):
    """-100 @ 1450, then BUY 250 @ 1400 -> +150 @ 1400, +5,000."""
    await engine.place_order(
        side=OrderSide.SHORT_SELL, quantity=100, reference_price=D("1450")
    )

    result = await engine.place_order(
        side=OrderSide.BUY, quantity=250, reference_price=D("1400")
    )

    assert result.position.quantity == 150
    assert result.position.average_price == D("1400.0000")
    assert result.gross_pnl == D("5000.00")


# --------------------------------------------------------------------------
# Realized P&L accumulation
# --------------------------------------------------------------------------


async def test_realized_pnl_accumulates_across_round_trips(engine, session):
    """The specification's four-order sequence: 5,000 + 5,000."""
    await engine.place_order(
        side=OrderSide.BUY, quantity=100, reference_price=D("1400")
    )
    await engine.place_order(
        side=OrderSide.SELL, quantity=100, reference_price=D("1450")
    )
    await engine.place_order(
        side=OrderSide.SHORT_SELL, quantity=100, reference_price=D("1450")
    )
    result = await engine.place_order(
        side=OrderSide.BUY, quantity=100, reference_price=D("1400")
    )

    assert result.position.quantity == 0
    assert result.position.realized_pnl == D("10000.00")
    assert await _cash(session) == D("1010000.00")


async def test_realized_pnl_survives_going_flat(engine):
    """Cumulative P&L is a running total, not a property of the open position."""
    await engine.place_order(
        side=OrderSide.BUY, quantity=10, reference_price=D("100")
    )
    await engine.place_order(
        side=OrderSide.SELL, quantity=10, reference_price=D("110")
    )
    result = await engine.place_order(
        side=OrderSide.BUY, quantity=10, reference_price=D("100")
    )

    assert result.position.quantity == 10
    assert result.position.realized_pnl == D("100.00")


async def test_trade_rows_carry_the_pnl_of_their_own_fill(engine, session):
    await engine.place_order(
        side=OrderSide.BUY, quantity=100, reference_price=D("1400")
    )
    await engine.place_order(
        side=OrderSide.SELL, quantity=100, reference_price=D("1450")
    )

    trades = (
        (await session.execute(select(Trade).order_by(Trade.id))).scalars().all()
    )

    assert len(trades) == 2
    assert trades[0].gross_pnl == D("0.00"), "the opening fill realizes nothing"
    assert trades[0].closed_quantity == 0
    assert trades[1].gross_pnl == D("5000.00")
    assert trades[1].closed_quantity == 100


# --------------------------------------------------------------------------
# Invalid orders
# --------------------------------------------------------------------------


@pytest.mark.parametrize("quantity", [0, -1, -100])
async def test_non_positive_quantity_is_rejected(engine, quantity):
    with pytest.raises(InvalidOrderError):
        await engine.place_order(
            side=OrderSide.BUY, quantity=quantity, reference_price=D("1400")
        )


async def test_quantity_beyond_the_bound_is_rejected(engine):
    with pytest.raises(InvalidOrderError):
        await engine.place_order(
            side=OrderSide.BUY, quantity=10_000_001, reference_price=D("1400")
        )


@pytest.mark.parametrize("price", ["0", "-1400"])
async def test_non_positive_price_is_rejected(engine, price):
    with pytest.raises(InvalidOrderError):
        await engine.place_order(
            side=OrderSide.BUY, quantity=100, reference_price=D(price)
        )


async def test_foreign_symbol_is_rejected(engine):
    with pytest.raises(UnsupportedSymbolError):
        await engine.place_order(
            side=OrderSide.BUY,
            quantity=100,
            reference_price=D("1400"),
            symbol="TCS",
        )


async def test_sell_without_a_long_is_rejected(engine):
    """Selling from flat would open a short; that must be stated explicitly."""
    with pytest.raises(InvalidPositionOperationError):
        await engine.place_order(
            side=OrderSide.SELL, quantity=100, reference_price=D("1450")
        )


async def test_selling_more_than_held_is_rejected(engine):
    await engine.place_order(
        side=OrderSide.BUY, quantity=100, reference_price=D("1400")
    )

    with pytest.raises(InvalidPositionOperationError):
        await engine.place_order(
            side=OrderSide.SELL, quantity=150, reference_price=D("1450")
        )


async def test_cover_without_a_short_is_rejected(engine):
    with pytest.raises(InvalidPositionOperationError):
        await engine.place_order(
            side=OrderSide.BUY_TO_COVER, quantity=100, reference_price=D("1400")
        )


async def test_covering_more_than_shorted_is_rejected(engine):
    await engine.place_order(
        side=OrderSide.SHORT_SELL, quantity=100, reference_price=D("1450")
    )

    with pytest.raises(InvalidPositionOperationError):
        await engine.place_order(
            side=OrderSide.BUY_TO_COVER, quantity=150, reference_price=D("1400")
        )


async def test_order_without_a_wallet_is_rejected(unfunded_engine):
    with pytest.raises(WalletNotFoundError):
        await unfunded_engine.place_order(
            side=OrderSide.BUY, quantity=1, reference_price=D("1400")
        )


# --------------------------------------------------------------------------
# Insufficient cash
# --------------------------------------------------------------------------


async def test_buy_beyond_the_balance_is_rejected(engine):
    """1,000 @ 1400 = 1,400,000 against a 1,000,000 wallet."""
    with pytest.raises(InsufficientFundsError):
        await engine.place_order(
            side=OrderSide.BUY, quantity=1000, reference_price=D("1400")
        )


async def test_a_rejected_order_leaves_cash_and_position_untouched(engine, session):
    with pytest.raises(InsufficientFundsError):
        await engine.place_order(
            side=OrderSide.BUY, quantity=1000, reference_price=D("1400")
        )

    assert await _cash(session) == D("1000000.00")
    position = (await session.execute(select(Position))).scalar_one_or_none()
    assert position is None or position.quantity == 0


async def test_a_buy_for_exactly_the_balance_is_allowed(engine, session):
    result = await engine.place_order(
        side=OrderSide.BUY, quantity=1000, reference_price=D("1000")
    )

    assert result.position.quantity == 1000
    assert await _cash(session) == D("0.00")


async def test_short_proceeds_fund_a_later_buy(engine, session):
    """Cash credited by a short is spendable, per the documented cash model."""
    await engine.place_order(
        side=OrderSide.SHORT_SELL, quantity=500, reference_price=D("1400")
    )

    result = await engine.place_order(
        side=OrderSide.BUY, quantity=1000, reference_price=D("1400")
    )

    assert result.position.quantity == 500
    assert await _cash(session) == D("300000.00")


# --------------------------------------------------------------------------
# Persistence, audit trail and atomicity
# --------------------------------------------------------------------------


async def test_a_fill_writes_order_trade_and_position(engine, session):
    await engine.place_order(
        side=OrderSide.BUY, quantity=100, reference_price=D("1400")
    )

    assert (await session.execute(select(func.count(Order.id)))).scalar_one() == 1
    assert (await session.execute(select(func.count(Trade.id)))).scalar_one() == 1
    assert (
        await session.execute(select(func.count(Position.symbol)))
    ).scalar_one() == 1


async def test_a_filled_order_records_its_execution_price(engine, session):
    await engine.place_order(
        side=OrderSide.BUY,
        quantity=100,
        reference_price=D("1400"),
        requested_price=D("1399"),
    )

    order = (await session.execute(select(Order))).scalar_one()

    assert order.status is OrderStatus.FILLED
    assert order.execution_price == D("1400.00")
    assert order.requested_price == D("1399.00")
    assert order.filled_at is not None


async def test_rejected_orders_are_kept_for_audit(engine, session):
    with pytest.raises(InsufficientFundsError):
        await engine.place_order(
            side=OrderSide.BUY, quantity=1000, reference_price=D("1400")
        )

    order = (await session.execute(select(Order))).scalar_one()

    assert order.status is OrderStatus.REJECTED
    assert order.execution_price is None
    assert "wallet holds" in order.rejection_reason


async def test_a_rejected_order_writes_no_trade(engine, session):
    with pytest.raises(InsufficientFundsError):
        await engine.place_order(
            side=OrderSide.BUY, quantity=1000, reference_price=D("1400")
        )

    assert (await session.execute(select(func.count(Trade.id)))).scalar_one() == 0


async def test_position_and_cash_stay_consistent_across_many_orders(engine, session):
    """Cash must equal the opening balance plus every realized P&L, once flat."""
    for side, quantity, price in (
        (OrderSide.BUY, 100, "1400"),
        (OrderSide.BUY, 50, "1420"),
        (OrderSide.SELL, 30, "1450"),
        (OrderSide.SELL, 120, "1460"),
        (OrderSide.SHORT_SELL, 80, "1470"),
        (OrderSide.BUY_TO_COVER, 80, "1440"),
    ):
        await engine.place_order(
            side=side, quantity=quantity, reference_price=D(price)
        )

    position = (await session.execute(select(Position))).scalar_one()
    assert position.quantity == 0

    expected_cash = D("1000000.00") + position.realized_pnl
    assert await _cash(session) == expected_cash


# --------------------------------------------------------------------------
# Portfolio valuation
# --------------------------------------------------------------------------


async def test_portfolio_values_an_open_long_at_the_mark_price(engine):
    await engine.place_order(
        side=OrderSide.BUY, quantity=100, reference_price=D("1400")
    )

    snapshot = await engine.get_portfolio(mark_price=D("1450"))

    assert snapshot.quantity == 100
    assert snapshot.unrealized_pnl == D("5000.00")
    assert snapshot.position_value == D("145000.00")
    assert snapshot.cash_balance == D("860000.00")
    assert snapshot.total_equity == D("1005000.00")


async def test_portfolio_values_an_open_short_as_a_liability(engine):
    await engine.place_order(
        side=OrderSide.SHORT_SELL, quantity=100, reference_price=D("1450")
    )

    snapshot = await engine.get_portfolio(mark_price=D("1400"))

    assert snapshot.quantity == -100
    assert snapshot.unrealized_pnl == D("5000.00")
    assert snapshot.position_value == D("-140000.00")
    assert snapshot.total_equity == D("1005000.00")


async def test_portfolio_without_a_mark_price_reports_no_unrealized_pnl(engine):
    await engine.place_order(
        side=OrderSide.BUY, quantity=100, reference_price=D("1400")
    )

    snapshot = await engine.get_portfolio()

    assert snapshot.mark_price is None
    assert snapshot.unrealized_pnl == D("0.00")
    assert snapshot.position_value == D("0.00")


async def test_position_reads_flat_before_any_trade(engine):
    position = await engine.get_position()

    assert position.quantity == 0
    assert position.average_price == D("0.0000")
    assert position.realized_pnl == D("0.00")


# --------------------------------------------------------------------------
# Transaction atomicity
# --------------------------------------------------------------------------


async def test_a_failure_mid_order_rolls_back_every_table(engine, session, monkeypatch):
    """The requirement: an order cannot partially update wallet or position.

    A fill touches four tables. This injects a failure after the position and
    cash have already been mutated in the session but before COMMIT, and
    asserts that none of it reached the database.
    """
    from app.trading.order_manager import OrderManager

    async def boom(self, order, execution_price):
        raise RuntimeError("database died mid-order")

    monkeypatch.setattr(OrderManager, "mark_filled", boom)

    with pytest.raises(RuntimeError, match="database died"):
        await engine.place_order(
            side=OrderSide.BUY, quantity=100, reference_price=D("1400")
        )

    await session.rollback()

    assert await _cash(session) == D("1000000.00"), "cash must be untouched"
    position = (await session.execute(select(Position))).scalar_one_or_none()
    assert position is None or position.quantity == 0
    assert (await session.execute(select(func.count(Order.id)))).scalar_one() == 0
    assert (await session.execute(select(func.count(Trade.id)))).scalar_one() == 0


async def test_a_failure_after_the_position_moves_leaves_no_trace(
    engine, session, monkeypatch
):
    """Same guarantee, with the failure injected one step earlier."""
    from app.trading.execution import ExecutionEngine

    async def boom(self, **kwargs):
        raise RuntimeError("trade insert failed")

    monkeypatch.setattr(ExecutionEngine, "record_trade", boom)

    with pytest.raises(RuntimeError, match="trade insert failed"):
        await engine.place_order(
            side=OrderSide.SHORT_SELL, quantity=100, reference_price=D("1450")
        )

    await session.rollback()

    assert await _cash(session) == D("1000000.00")
    position = (await session.execute(select(Position))).scalar_one_or_none()
    assert position is None or position.quantity == 0
