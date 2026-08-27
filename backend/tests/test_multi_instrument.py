"""Multi-instrument trading.

One wallet, many stocks. Covers the instrument registry, the search API, and
that positions, stop-losses and triggers stay independent per symbol.
"""

from decimal import Decimal

import pytest
from httpx import AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.pool import NullPool

from app.automation.monitor import AutomaticOrderMonitor
from app.automation.service import AutomaticOrderService
from app.core.config import settings
from app.core.exceptions import UnsupportedSymbolError
from app.market_data.instruments import (
    InstrumentRegistry,
    instrument_registry,
    resolve_instrument,
    resolve_symbol,
)
from app.models.automatic_order import (
    AutomaticOrderStatus,
    AutomaticOrderType,
    TriggerCondition,
)
from app.models.enums import OrderSide
from app.models.trading import Position
from app.repositories.wallet_repository import WalletRepository
from app.trading.engine import TradingEngine
from app.trading.execution import ExecutionEngine

D = Decimal


async def _wallet(session: AsyncSession, amount: str = "5000000.00") -> None:
    await WalletRepository(session).create(D(amount), settings.WALLET_CURRENCY)
    await session.commit()


def _engine(session: AsyncSession) -> TradingEngine:
    """Frictionless, so fills land at exact prices and totals are hand-checkable."""
    return TradingEngine(session, execution=ExecutionEngine.frictionless(session))


async def _buy(session, symbol, qty, price):
    return await _engine(session).place_order(
        side=OrderSide.BUY, quantity=qty, reference_price=D(price), symbol=symbol
    )


async def _short(session, symbol, qty, price):
    return await _engine(session).place_order(
        side=OrderSide.SHORT_SELL, quantity=qty, reference_price=D(price), symbol=symbol
    )


# ==========================================================================
# Registry -- pure
# ==========================================================================


def test_registry_contains_more_than_one_instrument():
    symbols = {instrument.symbol for instrument in instrument_registry.all()}
    assert {"RELIANCE", "TCS", "INFY", "HDFCBANK"} <= symbols


def test_search_by_symbol_ranks_the_exact_match_first():
    results = instrument_registry.search("TCS")
    assert results[0].symbol == "TCS"
    assert results[0].company_name == "Tata Consultancy Services"


def test_search_by_company_name():
    results = instrument_registry.search("reliance")
    assert results[0].symbol == "RELIANCE"


def test_search_is_case_insensitive_and_partial():
    assert any(i.symbol == "HDFCBANK" for i in instrument_registry.search("hdfc"))
    assert any(i.symbol == "INFY" for i in instrument_registry.search("Infos"))


def test_search_with_no_query_returns_the_catalogue():
    assert len(instrument_registry.search(None)) > 1
    assert len(instrument_registry.search("   ")) > 1


def test_search_for_nonsense_returns_nothing():
    assert instrument_registry.search("zzzznotacompany") == []


def test_resolve_defaults_to_the_configured_instrument():
    assert resolve_symbol(None) == settings.TRADING_SYMBOL


def test_resolve_is_case_insensitive():
    assert resolve_symbol("tcs") == "TCS"


def test_resolve_rejects_a_symbol_outside_the_universe():
    with pytest.raises(UnsupportedSymbolError, match="not a supported instrument"):
        resolve_symbol("AAPL")


def test_resolve_carries_the_exchange_from_the_instrument():
    assert resolve_instrument("INFY").exchange == "NSE"


def test_availability_is_cached_per_symbol():
    registry = InstrumentRegistry()
    assert registry.cached_availability("TCS") is None
    registry.remember_availability("TCS", True)
    assert registry.cached_availability("tcs") is True
    registry.reset_availability()
    assert registry.cached_availability("TCS") is None


# ==========================================================================
# Instrument API
# ==========================================================================


async def test_api_lists_instruments(client: AsyncClient):
    response = await client.get("/api/v1/instruments")
    assert response.status_code == 200
    rows = response.json()
    assert len(rows) > 1
    assert {"symbol", "company_name", "exchange", "instrument_type"} <= set(rows[0])


async def test_api_search_by_symbol(client: AsyncClient):
    response = await client.get("/api/v1/instruments", params={"search": "TCS"})
    assert response.status_code == 200
    assert response.json()[0]["symbol"] == "TCS"


async def test_api_search_by_company_name(client: AsyncClient):
    response = await client.get("/api/v1/instruments", params={"search": "infosys"})
    assert response.json()[0]["symbol"] == "INFY"


async def test_api_search_with_no_match_is_empty(client: AsyncClient):
    response = await client.get(
        "/api/v1/instruments", params={"search": "zzzznotacompany"}
    )
    assert response.json() == []


async def test_api_rejects_an_unsupported_symbol(client: AsyncClient):
    response = await client.get("/api/v1/instruments/AAPL")
    assert response.status_code == 400
    assert response.json()["error"]["code"] == "unsupported_symbol"


# ==========================================================================
# Independent positions per stock
# ==========================================================================


async def test_positions_are_independent_per_stock(session: AsyncSession):
    """BUY 100 RELIANCE, BUY 20 TCS, SHORT 50 INFY -- three separate positions."""
    await _wallet(session)

    await _buy(session, "RELIANCE", 100, "1400.00")
    await _buy(session, "TCS", 20, "3200.00")
    await _short(session, "INFY", 50, "1500.00")

    positions = {p.symbol: p for p in await _engine(session).list_positions()}

    assert positions["RELIANCE"].quantity == 100
    assert positions["RELIANCE"].average_price == D("1400.0000")
    assert positions["TCS"].quantity == 20
    assert positions["TCS"].average_price == D("3200.0000")
    assert positions["INFY"].quantity == -50
    assert positions["INFY"].average_price == D("1500.0000")


async def test_trading_one_stock_does_not_touch_another(session: AsyncSession):
    await _wallet(session)
    await _buy(session, "RELIANCE", 100, "1400.00")
    await _buy(session, "TCS", 20, "3200.00")

    # Close RELIANCE entirely.
    await _engine(session).place_order(
        side=OrderSide.SELL, quantity=100, reference_price=D("1450.00"), symbol="RELIANCE"
    )

    positions = {p.symbol: p for p in await _engine(session).list_positions()}
    assert positions["RELIANCE"].quantity == 0
    assert positions["TCS"].quantity == 20  # untouched
    assert positions["TCS"].average_price == D("3200.0000")


async def test_switching_back_finds_the_earlier_position(session: AsyncSession):
    """Switching instruments is a view change; nothing is deleted."""
    await _wallet(session)
    await _buy(session, "RELIANCE", 100, "1400.00")
    await _buy(session, "TCS", 20, "3200.00")
    await _buy(session, "INFY", 10, "1500.00")

    reliance = await _engine(session).get_position("RELIANCE")
    assert reliance.quantity == 100
    assert reliance.average_price == D("1400.0000")


async def test_orders_and_trades_carry_their_symbol(session: AsyncSession):
    await _wallet(session)
    await _buy(session, "TCS", 20, "3200.00")
    result = await _buy(session, "INFY", 10, "1500.00")

    assert result.order.symbol == "INFY"
    assert result.trade.symbol == "INFY"
    assert result.position.symbol == "INFY"

    orders = await _engine(session).list_orders()
    assert {order.symbol for order in orders} == {"TCS", "INFY"}


# ==========================================================================
# Portfolio aggregation across stocks
# ==========================================================================


async def test_portfolio_summary_aggregates_every_stock(session: AsyncSession):
    await _wallet(session, "5000000.00")
    await _buy(session, "RELIANCE", 100, "1400.00")  # -140,000
    await _buy(session, "TCS", 20, "3200.00")  # -64,000
    await _short(session, "INFY", 50, "1500.00")  # +75,000

    summary = await _engine(session).get_portfolio_summary(
        mark_prices={
            "RELIANCE": D("1450.00"),  # +5,000 unrealized
            "TCS": D("3300.00"),  # +2,000 unrealized
            "INFY": D("1400.00"),  # +5,000 unrealized (short, price fell)
        }
    )

    assert summary.cash_balance == D("4871000.00")  # 5,000,000 -140k -64k +75k
    assert summary.unrealized_pnl == D("12000.00")  # 5,000 + 2,000 + 5,000
    assert summary.position_value == D("141000.00")  # 145,000 + 66,000 - 70,000
    assert summary.total_equity == D("5012000.00")  # 4,871,000 + 141,000
    assert {p.symbol for p in summary.positions} == {"RELIANCE", "TCS", "INFY"}
    assert summary.unpriced_symbols == []


async def test_realized_pnl_sums_across_stocks(session: AsyncSession):
    await _wallet(session)
    await _buy(session, "RELIANCE", 100, "1400.00")
    await _engine(session).place_order(
        side=OrderSide.SELL, quantity=100, reference_price=D("1450.00"), symbol="RELIANCE"
    )  # +5,000
    await _buy(session, "TCS", 20, "3200.00")
    await _engine(session).place_order(
        side=OrderSide.SELL, quantity=20, reference_price=D("3100.00"), symbol="TCS"
    )  # -2,000

    summary = await _engine(session).get_portfolio_summary()
    assert summary.realized_pnl == D("3000.00")  # 5,000 - 2,000


async def test_an_open_position_without_a_mark_is_reported_unpriced(
    session: AsyncSession,
):
    await _wallet(session)
    await _buy(session, "RELIANCE", 100, "1400.00")
    await _buy(session, "TCS", 20, "3200.00")

    summary = await _engine(session).get_portfolio_summary(
        mark_prices={"RELIANCE": D("1450.00")}
    )

    assert summary.unpriced_symbols == ["TCS"]
    assert summary.unrealized_pnl == D("5000.00")  # TCS contributes nothing


async def test_portfolio_summary_api(client: AsyncClient, session: AsyncSession):
    await _wallet(session)
    await _buy(session, "RELIANCE", 100, "1400.00")
    await _buy(session, "TCS", 20, "3200.00")

    response = await client.get(
        "/api/v1/trading/portfolio/summary",
        params={"marks": "RELIANCE:1450.00,TCS:3300.00"},
    )
    assert response.status_code == 200
    body = response.json()
    assert body["unrealized_pnl"] == "7000.00"
    assert {p["symbol"] for p in body["positions"]} == {"RELIANCE", "TCS"}


async def test_portfolio_summary_rejects_a_bad_mark(client: AsyncClient, session):
    await _wallet(session)
    response = await client.get(
        "/api/v1/trading/portfolio/summary", params={"marks": "RELIANCE"}
    )
    assert response.status_code == 400
    assert response.json()["error"]["code"] == "invalid_order"


async def test_positions_endpoint_lists_every_stock(client: AsyncClient, session):
    await _wallet(session)
    await _buy(session, "RELIANCE", 100, "1400.00")
    await _buy(session, "TCS", 20, "3200.00")

    response = await client.get("/api/v1/trading/positions")
    assert response.status_code == 200
    assert {row["symbol"] for row in response.json()} == {"RELIANCE", "TCS"}


# ==========================================================================
# Stock-specific automatic orders
# ==========================================================================


async def test_a_stop_loss_belongs_to_its_own_stock(session: AsyncSession):
    """A TCS stop must not fire on a RELIANCE price."""
    await _wallet(session)
    await _buy(session, "RELIANCE", 100, "1400.00")
    await _buy(session, "TCS", 20, "3200.00")

    tcs_stop = await AutomaticOrderService(session).create(
        order_type=AutomaticOrderType.STOP_LOSS,
        trigger_price=D("3100.00"),
        trigger_condition=TriggerCondition.LTE,
        action=OrderSide.SELL,
        quantity=20,
        symbol="TCS",
    )

    # A RELIANCE tick well below the TCS trigger must not fire it.
    assert (
        await AutomaticOrderMonitor().on_price(
            market_price=D("1300.00"), symbol="RELIANCE"
        )
        == []
    )
    await session.refresh(tcs_stop)
    assert tcs_stop.status is AutomaticOrderStatus.ACTIVE

    # The matching TCS tick does.
    events = await AutomaticOrderMonitor().on_price(
        market_price=D("3099.00"), symbol="TCS"
    )
    assert len(events) == 1
    await session.refresh(tcs_stop)
    assert tcs_stop.status is AutomaticOrderStatus.TRIGGERED

    positions = {p.symbol: p for p in await _engine(session).list_positions()}
    assert positions["TCS"].quantity == 0
    assert positions["RELIANCE"].quantity == 100  # untouched


async def test_stop_loss_validation_uses_the_right_stocks_position(
    session: AsyncSession,
):
    """A short INFY stop must be GTE/COVER even while RELIANCE is long."""
    await _wallet(session)
    await _buy(session, "RELIANCE", 100, "1400.00")
    await _short(session, "INFY", 50, "1500.00")

    order = await AutomaticOrderService(session).create(
        order_type=AutomaticOrderType.STOP_LOSS,
        trigger_price=D("1550.00"),
        trigger_condition=TriggerCondition.GTE,
        action=OrderSide.BUY_TO_COVER,
        quantity=50,
        symbol="INFY",
    )
    assert order.status is AutomaticOrderStatus.ACTIVE
    assert order.symbol == "INFY"


async def test_closing_one_stock_only_retires_its_own_stop(session: AsyncSession):
    await _wallet(session)
    await _buy(session, "RELIANCE", 100, "1400.00")
    await _buy(session, "TCS", 20, "3200.00")

    service = AutomaticOrderService(session)
    reliance_stop = await service.create(
        order_type=AutomaticOrderType.STOP_LOSS,
        trigger_price=D("1350.00"),
        trigger_condition=TriggerCondition.LTE,
        action=OrderSide.SELL,
        quantity=100,
        symbol="RELIANCE",
    )
    tcs_stop = await service.create(
        order_type=AutomaticOrderType.STOP_LOSS,
        trigger_price=D("3100.00"),
        trigger_condition=TriggerCondition.LTE,
        action=OrderSide.SELL,
        quantity=20,
        symbol="TCS",
    )

    # Close RELIANCE manually.
    await _engine(session).place_order(
        side=OrderSide.SELL, quantity=100, reference_price=D("1450.00"), symbol="RELIANCE"
    )

    await session.refresh(reliance_stop)
    await session.refresh(tcs_stop)
    assert reliance_stop.status is AutomaticOrderStatus.CANCELLED
    assert tcs_stop.status is AutomaticOrderStatus.ACTIVE  # unaffected


# ==========================================================================
# Persistence
# ==========================================================================


async def test_multi_stock_state_survives_a_restart(session: AsyncSession):
    """Read back through a brand-new engine -- what a restart looks like."""
    await _wallet(session)
    await _buy(session, "RELIANCE", 100, "1400.00")
    await _buy(session, "TCS", 20, "3200.00")
    await _short(session, "INFY", 50, "1500.00")

    fresh_engine = create_async_engine(settings.DATABASE_URL, poolclass=NullPool)
    try:
        maker = async_sessionmaker(bind=fresh_engine, expire_on_commit=False)
        async with maker() as fresh:
            rows = list((await fresh.execute(select(Position))).scalars().all())
            by_symbol = {row.symbol: row.quantity for row in rows}
            assert by_symbol == {"RELIANCE": 100, "TCS": 20, "INFY": -50}
    finally:
        await fresh_engine.dispose()
