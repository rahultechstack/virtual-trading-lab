"""Portfolio snapshots and performance analytics, against real PostgreSQL.

Also covers the headline requirement of this stage: nothing is lost when the
process restarts. The persistence tests read back through a brand-new engine,
which is what a restart amounts to from the database's point of view.
"""

from decimal import Decimal

import pytest
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.pool import NullPool

from app.analytics.performance import PerformanceAnalyzer
from app.analytics.snapshots import SnapshotService
from app.core.config import settings
from app.core.exceptions import WalletNotFoundError
from app.models.enums import OrderSide
from app.models.portfolio_snapshot import PortfolioSnapshot, SnapshotSource
from app.models.trading import Order, Position, Trade
from app.services.wallet_service import WalletService
from app.trading.engine import TradingEngine
from app.trading.execution import ExecutionEngine
from app.trading.fees import FeeCalculator, Segment
from app.trading.slippage import SlippageModel
from app.trading.spread import SpreadModel

D = Decimal


def _execution(session) -> ExecutionEngine:
    """Deterministic costs so expected values can be worked by hand."""
    return ExecutionEngine(
        session,
        spread=SpreadModel(basis_points=D("20")),
        slippage=SlippageModel(basis_points=D("10")),
        fees=FeeCalculator(segment=Segment.INTRADAY),
    )


@pytest.fixture
async def engine(session) -> TradingEngine:
    await WalletService(session).initialize_wallet()
    return TradingEngine(session, execution=_execution(session))


@pytest.fixture
async def frictionless(session) -> TradingEngine:
    """No spread, slippage or charges -- gross equals net."""
    await WalletService(session).initialize_wallet()
    return TradingEngine(session, execution=ExecutionEngine.frictionless(session))


async def _fresh_read(statement):
    """Run a query through an engine the application never touched."""
    fresh_engine = create_async_engine(settings.DATABASE_URL, poolclass=NullPool)
    sessions = async_sessionmaker(bind=fresh_engine, class_=AsyncSession)
    try:
        async with sessions() as fresh_session:
            return (await fresh_session.execute(statement)).scalars().all()
    finally:
        await fresh_engine.dispose()


# ==========================================================================
# Snapshot capture
# ==========================================================================


async def test_capture_records_the_account_value(session):
    await WalletService(session).initialize_wallet()

    snapshot = await SnapshotService(session).capture()

    assert snapshot is not None
    assert snapshot.cash == D("1000000.00")
    assert snapshot.total_value == D("1000000.00")
    assert snapshot.quantity == 0
    assert snapshot.source is SnapshotSource.MANUAL


async def test_capture_values_an_open_long_at_the_mark(frictionless, session):
    await frictionless.place_order(
        side=OrderSide.BUY, quantity=100, reference_price=D("1000")
    )

    snapshot = await SnapshotService(session).capture(mark_price=D("1050"))

    assert snapshot is not None
    assert snapshot.quantity == 100
    assert snapshot.mark_price == D("1050.00")
    assert snapshot.position_value == D("105000.00")
    assert snapshot.unrealized_pnl == D("5000.00")
    # 900,000 cash + 105,000 position
    assert snapshot.total_value == D("1005000.00")


async def test_capture_values_a_short_as_a_negative_liability(frictionless, session):
    await frictionless.place_order(
        side=OrderSide.SHORT_SELL, quantity=100, reference_price=D("1000")
    )

    snapshot = await SnapshotService(session).capture(mark_price=D("950"))

    assert snapshot is not None
    assert snapshot.quantity == -100
    assert snapshot.position_value == D("-95000.00")
    assert snapshot.unrealized_pnl == D("5000.00")


async def test_a_flat_position_needs_no_mark_price(frictionless, session):
    """Nothing to value, so the mark is ignored and recorded as null."""
    snapshot = await SnapshotService(session).capture(mark_price=D("1050"))

    assert snapshot is not None
    assert snapshot.mark_price is None
    assert snapshot.position_value == D("0.00")
    assert snapshot.unrealized_pnl == D("0.00")


async def test_net_pnl_is_realized_less_charges_plus_unrealized(engine, session):
    await engine.place_order(
        side=OrderSide.BUY, quantity=100, reference_price=D("1000")
    )
    await engine.place_order(
        side=OrderSide.SELL, quantity=50, reference_price=D("1100")
    )

    snapshot = await SnapshotService(session).capture(mark_price=D("1100"))
    position = (await session.execute(select(Position))).scalar_one()

    assert snapshot is not None
    expected = (
        position.realized_pnl - position.total_charges + snapshot.unrealized_pnl
    )
    assert snapshot.net_pnl == expected


async def test_capture_without_a_wallet_is_refused(session):
    with pytest.raises(WalletNotFoundError):
        await SnapshotService(session).capture()


async def test_skip_if_unchanged_suppresses_a_duplicate(session):
    await WalletService(session).initialize_wallet()
    service = SnapshotService(session)

    first = await service.capture(source=SnapshotSource.PERIODIC)
    second = await service.capture(
        source=SnapshotSource.PERIODIC, skip_if_unchanged=True
    )

    assert first is not None
    assert second is None, "an idle account should not accumulate identical rows"
    assert await service.count() == 1


async def test_skip_if_unchanged_still_records_a_real_change(frictionless, session):
    """A moved price changes the valuation, so the row must be written.

    Note the mark differs from the fill price: the trade already snapshotted
    the account at 1000, so a periodic capture at that same price would be a
    genuine duplicate and is suppressed (see the test below).
    """
    service = SnapshotService(session)
    await frictionless.place_order(
        side=OrderSide.BUY, quantity=10, reference_price=D("1000")
    )
    before = await service.count()

    written = await service.capture(
        mark_price=D("1050"), source=SnapshotSource.PERIODIC, skip_if_unchanged=True
    )

    assert written is not None
    assert written.unrealized_pnl == D("500.00")
    assert await service.count() == before + 1


async def test_a_periodic_capture_at_the_fill_price_is_a_duplicate(
    frictionless, session
):
    """The trade snapshot already covers that exact state."""
    service = SnapshotService(session)
    await frictionless.place_order(
        side=OrderSide.BUY, quantity=10, reference_price=D("1000")
    )
    before = await service.count()

    written = await service.capture(
        mark_price=D("1000"), source=SnapshotSource.PERIODIC, skip_if_unchanged=True
    )

    assert written is None
    assert await service.count() == before


# ==========================================================================
# Snapshots taken with trades
# ==========================================================================


async def test_a_trade_writes_a_snapshot_in_the_same_transaction(
    frictionless, session
):
    await frictionless.place_order(
        side=OrderSide.BUY, quantity=100, reference_price=D("1000")
    )

    snapshots = (
        (await session.execute(select(PortfolioSnapshot))).scalars().all()
    )

    assert len(snapshots) == 1
    assert snapshots[0].source is SnapshotSource.TRADE
    assert snapshots[0].quantity == 100


async def test_the_trade_snapshot_is_marked_at_the_fill_price(frictionless, session):
    result = await frictionless.place_order(
        side=OrderSide.BUY, quantity=100, reference_price=D("1000")
    )

    snapshot = (await session.execute(select(PortfolioSnapshot))).scalar_one()

    assert snapshot.mark_price == result.trade.execution_price


async def test_a_rejected_order_writes_no_snapshot(frictionless, session):
    from app.core.exceptions import InsufficientFundsError

    with pytest.raises(InsufficientFundsError):
        await frictionless.place_order(
            side=OrderSide.BUY, quantity=100_000, reference_price=D("1000")
        )

    count = (
        await session.execute(select(func.count(PortfolioSnapshot.id)))
    ).scalar_one()
    assert count == 0


async def test_every_trade_leaves_a_point_on_the_curve(frictionless, session):
    for side, quantity, price in (
        (OrderSide.BUY, 100, "1000"),
        (OrderSide.SELL, 50, "1050"),
        (OrderSide.SELL, 50, "1100"),
    ):
        await frictionless.place_order(
            side=side, quantity=quantity, reference_price=D(price)
        )

    snapshots = await SnapshotService(session).history()

    assert len(snapshots) == 3
    assert [s.quantity for s in snapshots] == [100, 50, 0]


# ==========================================================================
# History reads
# ==========================================================================


async def test_history_is_returned_oldest_first(frictionless, session):
    for price in ("1000", "1010", "1020"):
        await frictionless.place_order(
            side=OrderSide.BUY, quantity=1, reference_price=D(price)
        )

    snapshots = await SnapshotService(session).history()

    timestamps = [s.captured_at for s in snapshots]
    assert timestamps == sorted(timestamps), "the curve must plot left to right"


async def test_a_narrow_limit_returns_the_most_recent_slice(frictionless, session):
    for _ in range(5):
        await frictionless.place_order(
            side=OrderSide.BUY, quantity=1, reference_price=D("1000")
        )

    service = SnapshotService(session)
    everything = await service.history()
    latest_two = await service.history(limit=2)

    assert len(latest_two) == 2
    assert latest_two[-1].id == everything[-1].id, "kept the newest, not the oldest"


async def test_history_can_be_filtered_by_source(frictionless, session):
    await frictionless.place_order(
        side=OrderSide.BUY, quantity=1, reference_price=D("1000")
    )
    service = SnapshotService(session)
    await service.capture(mark_price=D("1000"), source=SnapshotSource.MANUAL)

    trade_only = await service.history(source=SnapshotSource.TRADE)

    assert len(trade_only) == 1
    assert trade_only[0].source is SnapshotSource.TRADE


# ==========================================================================
# Persistence across a restart
# ==========================================================================


async def test_everything_survives_a_simulated_restart(engine, session):
    """The headline requirement: a restart resets nothing."""
    await engine.place_order(
        side=OrderSide.BUY, quantity=100, reference_price=D("1000")
    )
    await engine.place_order(
        side=OrderSide.SELL, quantity=100, reference_price=D("1100")
    )
    await SnapshotService(session).capture(source=SnapshotSource.MANUAL)

    orders = await _fresh_read(select(Order))
    trades = await _fresh_read(select(Trade))
    positions = await _fresh_read(select(Position))
    snapshots = await _fresh_read(select(PortfolioSnapshot))

    assert len(orders) == 2
    assert len(trades) == 2
    assert len(positions) == 1
    assert len(snapshots) == 3, "two trade snapshots plus the manual one"


async def test_realized_pnl_and_charges_survive_a_restart(engine, session):
    await engine.place_order(
        side=OrderSide.BUY, quantity=100, reference_price=D("1000")
    )
    await engine.place_order(
        side=OrderSide.SELL, quantity=100, reference_price=D("1100")
    )
    expected = (await session.execute(select(Position))).scalar_one()
    realized, charges, net = (
        expected.realized_pnl,
        expected.total_charges,
        expected.net_realized_pnl,
    )

    reloaded = (await _fresh_read(select(Position)))[0]

    assert reloaded.realized_pnl == realized
    assert reloaded.total_charges == charges
    assert reloaded.net_realized_pnl == net


async def test_the_equity_curve_survives_a_restart(frictionless, session):
    for price in ("1000", "1050", "1100"):
        await frictionless.place_order(
            side=OrderSide.BUY, quantity=10, reference_price=D(price)
        )
    expected = [s.total_value for s in await SnapshotService(session).history()]

    reloaded = await _fresh_read(
        select(PortfolioSnapshot).order_by(PortfolioSnapshot.id)
    )

    assert [s.total_value for s in reloaded] == expected


# ==========================================================================
# Performance summary
# ==========================================================================


async def test_summary_of_an_empty_account(session):
    summary = await PerformanceAnalyzer(session).summary()

    assert summary.total_trades == 0
    assert summary.closing_trades == 0
    assert summary.win_rate is None
    assert summary.total_net_pnl == D("0.00")
    assert summary.largest_winning_trade is None
    assert summary.largest_losing_trade is None


async def test_opening_fills_are_not_counted_as_wins_or_losses(
    frictionless, session
):
    """An entry realizes nothing; counting it would distort the win rate."""
    await frictionless.place_order(
        side=OrderSide.BUY, quantity=100, reference_price=D("1000")
    )

    summary = await PerformanceAnalyzer(session).summary()

    assert summary.total_trades == 1
    assert summary.closing_trades == 0
    assert summary.winning_trades == 0
    assert summary.losing_trades == 0
    assert summary.win_rate is None


async def test_win_and_loss_counts(frictionless, session):
    # Two winners and one loser.
    for entry, exit_ in (("1000", "1100"), ("1000", "1100"), ("1000", "900")):
        await frictionless.place_order(
            side=OrderSide.BUY, quantity=10, reference_price=D(entry)
        )
        await frictionless.place_order(
            side=OrderSide.SELL, quantity=10, reference_price=D(exit_)
        )

    summary = await PerformanceAnalyzer(session).summary()

    assert summary.total_trades == 6
    assert summary.closing_trades == 3
    assert summary.winning_trades == 2
    assert summary.losing_trades == 1
    assert summary.win_rate == D("66.67")


async def test_totals_reconcile(frictionless, session):
    await frictionless.place_order(
        side=OrderSide.BUY, quantity=100, reference_price=D("1000")
    )
    await frictionless.place_order(
        side=OrderSide.SELL, quantity=100, reference_price=D("1100")
    )

    summary = await PerformanceAnalyzer(session).summary()

    assert summary.total_gross_pnl == D("10000.00")
    assert summary.total_net_pnl == summary.total_gross_pnl - summary.total_charges


async def test_charges_from_opening_fills_are_included(engine, session):
    """Entering a position costs money even though it realizes nothing."""
    await engine.place_order(
        side=OrderSide.BUY, quantity=100, reference_price=D("1000")
    )

    summary = await PerformanceAnalyzer(session).summary()

    assert summary.total_trades == 1
    assert summary.closing_trades == 0
    assert summary.total_charges > 0
    assert summary.total_net_pnl < 0, "the entry cost its charges"


async def test_a_win_is_judged_on_net_not_gross(engine, session):
    """A gross-positive trade that charges swallow is a loss, not a win."""
    await engine.place_order(
        side=OrderSide.BUY, quantity=1, reference_price=D("1000")
    )
    await engine.place_order(
        side=OrderSide.SELL, quantity=1, reference_price=D("1000.60")
    )

    trades = list((await session.execute(select(Trade).order_by(Trade.id))).scalars())
    closing = trades[-1]
    summary = await PerformanceAnalyzer(session).summary()

    assert closing.net_pnl < 0
    assert summary.winning_trades == 0
    assert summary.losing_trades == 1


async def test_largest_winner_and_loser(frictionless, session):
    for entry, exit_, quantity in (
        ("1000", "1010", 10),
        ("1000", "1200", 10),
        ("1000", "800", 10),
    ):
        await frictionless.place_order(
            side=OrderSide.BUY, quantity=quantity, reference_price=D(entry)
        )
        await frictionless.place_order(
            side=OrderSide.SELL, quantity=quantity, reference_price=D(exit_)
        )

    summary = await PerformanceAnalyzer(session).summary()

    assert summary.largest_winning_trade is not None
    assert summary.largest_winning_trade.net_pnl == D("2000.00")
    assert summary.largest_losing_trade is not None
    assert summary.largest_losing_trade.net_pnl == D("-2000.00")


async def test_extremes_are_none_when_nothing_won_or_lost(frictionless, session):
    """A break-even round trip has no best or worst."""
    await frictionless.place_order(
        side=OrderSide.BUY, quantity=10, reference_price=D("1000")
    )
    await frictionless.place_order(
        side=OrderSide.SELL, quantity=10, reference_price=D("1000")
    )

    summary = await PerformanceAnalyzer(session).summary()

    assert summary.breakeven_trades == 1
    assert summary.largest_winning_trade is None
    assert summary.largest_losing_trade is None


async def test_profit_factor(frictionless, session):
    """Gross profit 3,000 over gross loss 1,000 -> 3.00."""
    await frictionless.place_order(
        side=OrderSide.BUY, quantity=10, reference_price=D("1000")
    )
    await frictionless.place_order(
        side=OrderSide.SELL, quantity=10, reference_price=D("1300")
    )
    await frictionless.place_order(
        side=OrderSide.BUY, quantity=10, reference_price=D("1000")
    )
    await frictionless.place_order(
        side=OrderSide.SELL, quantity=10, reference_price=D("900")
    )

    summary = await PerformanceAnalyzer(session).summary()

    assert summary.profit_factor == D("3.00")


async def test_profit_factor_is_none_without_a_loss(frictionless, session):
    await frictionless.place_order(
        side=OrderSide.BUY, quantity=10, reference_price=D("1000")
    )
    await frictionless.place_order(
        side=OrderSide.SELL, quantity=10, reference_price=D("1100")
    )

    summary = await PerformanceAnalyzer(session).summary()

    assert summary.profit_factor is None


async def test_order_counts_include_rejections(frictionless, session):
    from app.core.exceptions import InsufficientFundsError

    await frictionless.place_order(
        side=OrderSide.BUY, quantity=10, reference_price=D("1000")
    )
    with pytest.raises(InsufficientFundsError):
        await frictionless.place_order(
            side=OrderSide.BUY, quantity=100_000, reference_price=D("1000")
        )

    summary = await PerformanceAnalyzer(session).summary()

    assert summary.total_orders == 2
    assert summary.filled_orders == 1
    assert summary.rejected_orders == 1


async def test_the_summary_survives_a_restart(frictionless, session):
    await frictionless.place_order(
        side=OrderSide.BUY, quantity=10, reference_price=D("1000")
    )
    await frictionless.place_order(
        side=OrderSide.SELL, quantity=10, reference_price=D("1100")
    )
    expected = await PerformanceAnalyzer(session).summary()

    fresh_engine = create_async_engine(settings.DATABASE_URL, poolclass=NullPool)
    sessions = async_sessionmaker(bind=fresh_engine, class_=AsyncSession)
    try:
        async with sessions() as fresh_session:
            reloaded = await PerformanceAnalyzer(fresh_session).summary()
    finally:
        await fresh_engine.dispose()

    assert reloaded == expected
