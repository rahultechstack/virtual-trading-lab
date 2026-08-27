"""Automatic orders: stop-losses and price triggers.

Covers the trigger arithmetic in isolation, then the full path against a real
PostgreSQL database -- claim, execute through the ordinary trading engine,
reconcile against the position, and refuse to fire twice.
"""

from decimal import Decimal

import pytest
from httpx import AsyncClient
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.pool import NullPool

from app.automation.evaluator import (
    closing_side_for,
    condition_is_met,
    protects_position,
    stop_loss_condition_for,
)
from app.automation.monitor import AutomaticOrderMonitor
from app.automation.service import AutomaticOrderService
from app.core.config import settings
from app.core.exceptions import (
    AutomaticOrderNotFoundError,
    InvalidAutomaticOrderError,
    UnsupportedSymbolError,
)
from app.models.automatic_order import (
    AutomaticOrder,
    AutomaticOrderStatus,
    AutomaticOrderType,
    TriggerCondition,
)
from app.models.enums import OrderSide
from app.models.trading import Order, Position, Trade
from app.repositories.wallet_repository import WalletRepository
from app.trading.engine import TradingEngine
from app.trading.execution import ExecutionEngine

D = Decimal
URL = "/api/v1/automatic-orders"


# --------------------------------------------------------------------------
# Helpers
# --------------------------------------------------------------------------


async def _wallet(session: AsyncSession, amount: str = "1000000.00") -> None:
    await WalletRepository(session).create(D(amount), settings.WALLET_CURRENCY)
    await session.commit()


def _engine(session: AsyncSession) -> TradingEngine:
    """Frictionless engine, so set-up fills land at exact prices."""
    return TradingEngine(session, execution=ExecutionEngine.frictionless(session))


async def _open_long(session: AsyncSession, qty: int = 100, price: str = "1400.00"):
    return await _engine(session).place_order(
        side=OrderSide.BUY, quantity=qty, reference_price=D(price)
    )


async def _open_short(session: AsyncSession, qty: int = 100, price: str = "1400.00"):
    return await _engine(session).place_order(
        side=OrderSide.SHORT_SELL, quantity=qty, reference_price=D(price)
    )


async def _stop_loss(
    session: AsyncSession,
    *,
    trigger: str,
    condition: TriggerCondition,
    action: OrderSide,
    quantity: int = 100,
    reference_price: str | None = None,
) -> AutomaticOrder:
    return await AutomaticOrderService(session).create(
        order_type=AutomaticOrderType.STOP_LOSS,
        trigger_price=D(trigger),
        trigger_condition=condition,
        action=action,
        quantity=quantity,
        reference_price=D(reference_price) if reference_price else None,
    )


async def _price_trigger(
    session: AsyncSession,
    *,
    trigger: str,
    condition: TriggerCondition,
    action: OrderSide,
    quantity: int = 100,
) -> AutomaticOrder:
    return await AutomaticOrderService(session).create(
        order_type=AutomaticOrderType.PRICE_TRIGGER,
        trigger_price=D(trigger),
        trigger_condition=condition,
        action=action,
        quantity=quantity,
    )


def _monitor() -> AutomaticOrderMonitor:
    """A fresh monitor, so counters do not leak between tests."""
    return AutomaticOrderMonitor()


async def _position(session: AsyncSession) -> Position | None:
    return (
        await session.execute(
            select(Position).where(Position.symbol == settings.TRADING_SYMBOL)
        )
    ).scalar_one_or_none()


async def _trade_count(session: AsyncSession) -> int:
    return int((await session.execute(select(func.count(Trade.id)))).scalar_one())


# ==========================================================================
# Trigger arithmetic -- pure, no database
# ==========================================================================


@pytest.mark.parametrize(
    "condition,trigger,market,expected",
    [
        (TriggerCondition.GTE, D("1450"), D("1449.99"), False),
        (TriggerCondition.GTE, D("1450"), D("1450"), True),  # inclusive
        (TriggerCondition.GTE, D("1450"), D("1450.01"), True),
        (TriggerCondition.LTE, D("1350"), D("1350.01"), False),
        (TriggerCondition.LTE, D("1350"), D("1350"), True),  # inclusive
        (TriggerCondition.LTE, D("1350"), D("1349.99"), True),
    ],
)
def test_condition_boundaries_are_inclusive(condition, trigger, market, expected):
    assert (
        condition_is_met(
            condition=condition, trigger_price=trigger, market_price=market
        )
        is expected
    )


def test_closing_side_follows_the_position():
    assert closing_side_for(100) is OrderSide.SELL
    assert closing_side_for(-100) is OrderSide.BUY_TO_COVER
    assert closing_side_for(0) is None


def test_stop_loss_condition_follows_the_position():
    assert stop_loss_condition_for(100) is TriggerCondition.LTE
    assert stop_loss_condition_for(-100) is TriggerCondition.GTE
    assert stop_loss_condition_for(0) is None


def test_protects_position():
    assert protects_position(OrderSide.SELL, 100) is True
    assert protects_position(OrderSide.SELL, 0) is False
    assert protects_position(OrderSide.SELL, -100) is False
    assert protects_position(OrderSide.BUY_TO_COVER, -100) is True
    assert protects_position(OrderSide.BUY_TO_COVER, 100) is False


# ==========================================================================
# Long stop-loss
# ==========================================================================


async def test_long_stop_loss_sells_when_price_falls_through(session: AsyncSession):
    """BUY 100 @ 1400, stop 1350, price 1349 -> SELL 100."""
    await _wallet(session)
    await _open_long(session, 100, "1400.00")
    stop = await _stop_loss(
        session,
        trigger="1350.00",
        condition=TriggerCondition.LTE,
        action=OrderSide.SELL,
    )

    events = await _monitor().on_price(market_price=D("1349.00"))

    await session.refresh(stop)
    assert stop.status is AutomaticOrderStatus.TRIGGERED
    assert stop.triggered_at is not None
    assert stop.trigger_market_price == D("1349.00")
    assert stop.triggered_order_id is not None

    position = await _position(session)
    assert position is not None
    assert position.quantity == 0  # flat

    order = (await session.execute(select(Order).where(Order.id == stop.triggered_order_id))).scalar_one()
    assert order.side is OrderSide.SELL
    assert order.quantity == 100

    assert len(events) == 1
    assert events[0]["type"] == "automatic_order"
    assert events[0]["data"]["event"] == "triggered"


async def test_long_stop_loss_does_not_fire_above_trigger(session: AsyncSession):
    await _wallet(session)
    await _open_long(session)
    stop = await _stop_loss(
        session,
        trigger="1350.00",
        condition=TriggerCondition.LTE,
        action=OrderSide.SELL,
    )

    assert await _monitor().on_price(market_price=D("1351.00")) == []

    await session.refresh(stop)
    assert stop.status is AutomaticOrderStatus.ACTIVE
    position = await _position(session)
    assert position.quantity == 100


# ==========================================================================
# Short stop-loss
# ==========================================================================


async def test_short_stop_loss_covers_when_price_rises_through(session: AsyncSession):
    """SHORT 100 @ 1400, stop 1450, price 1451 -> BUY_TO_COVER 100."""
    await _wallet(session)
    await _open_short(session, 100, "1400.00")
    stop = await _stop_loss(
        session,
        trigger="1450.00",
        condition=TriggerCondition.GTE,
        action=OrderSide.BUY_TO_COVER,
    )

    events = await _monitor().on_price(market_price=D("1451.00"))

    await session.refresh(stop)
    assert stop.status is AutomaticOrderStatus.TRIGGERED

    position = await _position(session)
    assert position.quantity == 0

    order = (await session.execute(select(Order).where(Order.id == stop.triggered_order_id))).scalar_one()
    assert order.side is OrderSide.BUY_TO_COVER
    assert order.quantity == 100
    assert len(events) == 1


async def test_short_stop_loss_does_not_fire_below_trigger(session: AsyncSession):
    await _wallet(session)
    await _open_short(session)
    stop = await _stop_loss(
        session,
        trigger="1450.00",
        condition=TriggerCondition.GTE,
        action=OrderSide.BUY_TO_COVER,
    )

    assert await _monitor().on_price(market_price=D("1449.00")) == []
    await session.refresh(stop)
    assert stop.status is AutomaticOrderStatus.ACTIVE


# ==========================================================================
# Price triggers, exact boundaries
# ==========================================================================


async def test_gte_trigger_fires_at_exactly_the_trigger_price(session: AsyncSession):
    await _wallet(session)
    await _open_long(session, 100, "1400.00")
    trigger = await _price_trigger(
        session,
        trigger="1450.00",
        condition=TriggerCondition.GTE,
        action=OrderSide.SELL,
    )

    await _monitor().on_price(market_price=D("1450.00"))

    await session.refresh(trigger)
    assert trigger.status is AutomaticOrderStatus.TRIGGERED


async def test_lte_trigger_fires_at_exactly_the_trigger_price(session: AsyncSession):
    await _wallet(session)
    trigger = await _price_trigger(
        session,
        trigger="1350.00",
        condition=TriggerCondition.LTE,
        action=OrderSide.BUY,
    )

    await _monitor().on_price(market_price=D("1350.00"))

    await session.refresh(trigger)
    assert trigger.status is AutomaticOrderStatus.TRIGGERED
    position = await _position(session)
    assert position.quantity == 100  # opened a long


# ==========================================================================
# Duplicate execution
# ==========================================================================


async def test_a_trigger_fires_exactly_once_across_many_ticks(session: AsyncSession):
    """Price stays past the trigger -- it must still execute only once."""
    await _wallet(session)
    await _open_long(session, 100, "1400.00")
    stop = await _stop_loss(
        session,
        trigger="1350.00",
        condition=TriggerCondition.LTE,
        action=OrderSide.SELL,
    )

    monitor = _monitor()
    first = await monitor.on_price(market_price=D("1350.00"))
    second = await monitor.on_price(market_price=D("1349.00"))
    third = await monitor.on_price(market_price=D("1348.00"))

    assert len(first) == 1
    assert second == []
    assert third == []

    await session.refresh(stop)
    assert stop.status is AutomaticOrderStatus.TRIGGERED
    assert monitor.triggered == 1

    # One opening trade plus exactly one triggered trade.
    assert await _trade_count(session) == 2


async def test_triggered_orders_leave_the_active_set(session: AsyncSession):
    await _wallet(session)
    await _open_long(session)
    await _stop_loss(
        session,
        trigger="1350.00",
        condition=TriggerCondition.LTE,
        action=OrderSide.SELL,
    )

    await _monitor().on_price(market_price=D("1349.00"))

    active = await AutomaticOrderService(session).list_active()
    assert active == []


# ==========================================================================
# Position interaction: manual close and partial close
# ==========================================================================


async def test_manual_close_cancels_the_stop_loss(session: AsyncSession):
    """LONG 100 with a stop; user sells all 100 manually -> stop retired."""
    await _wallet(session)
    await _open_long(session, 100, "1400.00")
    stop = await _stop_loss(
        session,
        trigger="1350.00",
        condition=TriggerCondition.LTE,
        action=OrderSide.SELL,
    )

    await _engine(session).place_order(
        side=OrderSide.SELL, quantity=100, reference_price=D("1420.00")
    )

    await session.refresh(stop)
    assert stop.status is AutomaticOrderStatus.CANCELLED
    assert stop.cancelled_at is not None
    assert "Position closed" in stop.reason

    # And it cannot fire afterwards, even at a matching price.
    assert await _monitor().on_price(market_price=D("1300.00")) == []
    position = await _position(session)
    assert position.quantity == 0


async def test_partial_close_clamps_the_stop_loss_quantity(session: AsyncSession):
    """LONG 100 with a stop for 100; user sells 40 -> stop becomes 60."""
    await _wallet(session)
    await _open_long(session, 100, "1400.00")
    stop = await _stop_loss(
        session,
        trigger="1350.00",
        condition=TriggerCondition.LTE,
        action=OrderSide.SELL,
        quantity=100,
    )

    await _engine(session).place_order(
        side=OrderSide.SELL, quantity=40, reference_price=D("1420.00")
    )

    await session.refresh(stop)
    assert stop.status is AutomaticOrderStatus.ACTIVE
    assert stop.quantity == 60  # clamped to what remains

    await _monitor().on_price(market_price=D("1349.00"))

    position = await _position(session)
    assert position.quantity == 0  # the remaining 60 were stopped out
    await session.refresh(stop)
    assert stop.status is AutomaticOrderStatus.TRIGGERED


async def test_position_reversal_retires_the_stop_loss(session: AsyncSession):
    """A SHORT through zero leaves a long's stop meaningless."""
    await _wallet(session)
    await _open_long(session, 100, "1400.00")
    stop = await _stop_loss(
        session,
        trigger="1350.00",
        condition=TriggerCondition.LTE,
        action=OrderSide.SELL,
    )

    await _engine(session).place_order(
        side=OrderSide.SHORT_SELL, quantity=150, reference_price=D("1420.00")
    )

    await session.refresh(stop)
    assert stop.status is AutomaticOrderStatus.CANCELLED
    assert "reversed" in stop.reason.lower()


async def test_growing_a_position_leaves_the_stop_quantity_alone(session: AsyncSession):
    await _wallet(session)
    await _open_long(session, 100, "1400.00")
    stop = await _stop_loss(
        session,
        trigger="1350.00",
        condition=TriggerCondition.LTE,
        action=OrderSide.SELL,
        quantity=100,
    )

    await _open_long(session, 50, "1410.00")

    await session.refresh(stop)
    assert stop.status is AutomaticOrderStatus.ACTIVE
    assert stop.quantity == 100  # not raised to 150


# ==========================================================================
# Validation
# ==========================================================================


async def test_stop_loss_requires_an_open_position(session: AsyncSession):
    await _wallet(session)
    with pytest.raises(InvalidAutomaticOrderError, match="flat"):
        await _stop_loss(
            session,
            trigger="1350.00",
            condition=TriggerCondition.LTE,
            action=OrderSide.SELL,
        )


async def test_long_stop_loss_rejects_a_cover_action(session: AsyncSession):
    await _wallet(session)
    await _open_long(session)
    with pytest.raises(InvalidAutomaticOrderError, match="must act with"):
        await _stop_loss(
            session,
            trigger="1350.00",
            condition=TriggerCondition.LTE,
            action=OrderSide.BUY_TO_COVER,
        )


async def test_long_stop_loss_rejects_a_gte_condition(session: AsyncSession):
    await _wallet(session)
    await _open_long(session)
    with pytest.raises(InvalidAutomaticOrderError, match="triggers on"):
        await _stop_loss(
            session,
            trigger="1450.00",
            condition=TriggerCondition.GTE,
            action=OrderSide.SELL,
        )


async def test_short_stop_loss_rejects_a_sell_action(session: AsyncSession):
    await _wallet(session)
    await _open_short(session)
    with pytest.raises(InvalidAutomaticOrderError, match="must act with"):
        await _stop_loss(
            session,
            trigger="1450.00",
            condition=TriggerCondition.GTE,
            action=OrderSide.SELL,
        )


async def test_stop_loss_cannot_exceed_the_position(session: AsyncSession):
    await _wallet(session)
    await _open_long(session, 100, "1400.00")
    with pytest.raises(InvalidAutomaticOrderError, match="only 100"):
        await _stop_loss(
            session,
            trigger="1350.00",
            condition=TriggerCondition.LTE,
            action=OrderSide.SELL,
            quantity=150,
        )


async def test_long_stop_above_the_live_price_is_rejected(session: AsyncSession):
    """It would fire on the very next tick, which is never what was meant."""
    await _wallet(session)
    await _open_long(session, 100, "1400.00")
    with pytest.raises(InvalidAutomaticOrderError, match="below the current price"):
        await _stop_loss(
            session,
            trigger="1410.00",
            condition=TriggerCondition.LTE,
            action=OrderSide.SELL,
            reference_price="1405.00",
        )


async def test_long_stop_above_entry_is_allowed_once_price_has_risen(
    session: AsyncSession,
):
    """A profit-protecting stop is valid: above entry, below the live price."""
    await _wallet(session)
    await _open_long(session, 100, "1400.00")
    stop = await _stop_loss(
        session,
        trigger="1450.00",
        condition=TriggerCondition.LTE,
        action=OrderSide.SELL,
        reference_price="1500.00",
    )
    assert stop.status is AutomaticOrderStatus.ACTIVE


async def test_short_stop_below_the_live_price_is_rejected(session: AsyncSession):
    await _wallet(session)
    await _open_short(session, 100, "1400.00")
    with pytest.raises(InvalidAutomaticOrderError, match="above the current price"):
        await _stop_loss(
            session,
            trigger="1390.00",
            condition=TriggerCondition.GTE,
            action=OrderSide.BUY_TO_COVER,
            reference_price="1395.00",
        )


async def test_rejects_non_positive_quantity(session: AsyncSession):
    await _wallet(session)
    with pytest.raises(InvalidAutomaticOrderError, match="Quantity must be positive"):
        await _price_trigger(
            session,
            trigger="1350.00",
            condition=TriggerCondition.LTE,
            action=OrderSide.BUY,
            quantity=0,
        )


async def test_rejects_quantity_beyond_the_maximum(session: AsyncSession):
    await _wallet(session)
    with pytest.raises(InvalidAutomaticOrderError, match="exceeds the maximum"):
        await _price_trigger(
            session,
            trigger="1350.00",
            condition=TriggerCondition.LTE,
            action=OrderSide.BUY,
            quantity=10_000_001,
        )


async def test_rejects_non_positive_trigger_price(session: AsyncSession):
    await _wallet(session)
    with pytest.raises(InvalidAutomaticOrderError, match="Trigger price must be positive"):
        await _price_trigger(
            session,
            trigger="0.00",
            condition=TriggerCondition.LTE,
            action=OrderSide.BUY,
        )


async def test_rejects_another_symbol(session: AsyncSession):
    await _wallet(session)
    with pytest.raises(UnsupportedSymbolError):
        await AutomaticOrderService(session).create(
            order_type=AutomaticOrderType.PRICE_TRIGGER,
            trigger_price=D("1350.00"),
            trigger_condition=TriggerCondition.LTE,
            action=OrderSide.BUY,
            quantity=10,
            symbol="TCS",
        )


# ==========================================================================
# Failed execution
# ==========================================================================


async def test_execution_rejection_marks_the_order_failed(session: AsyncSession):
    """A trigger the engine refuses is terminal, so it cannot spin every tick."""
    await _wallet(session, "1000.00")  # nowhere near enough to buy 100
    trigger = await _price_trigger(
        session,
        trigger="1350.00",
        condition=TriggerCondition.LTE,
        action=OrderSide.BUY,
        quantity=100,
    )

    monitor = _monitor()
    events = await monitor.on_price(market_price=D("1349.00"))

    await session.refresh(trigger)
    assert trigger.status is AutomaticOrderStatus.FAILED
    assert trigger.reason is not None
    assert monitor.failed == 1
    assert events[0]["data"]["event"] == "failed"

    # Terminal: a later tick must not retry it.
    assert await monitor.on_price(market_price=D("1348.00")) == []


# ==========================================================================
# Cancellation
# ==========================================================================


async def test_cancel_marks_the_order_cancelled(session: AsyncSession):
    await _wallet(session)
    await _open_long(session)
    stop = await _stop_loss(
        session,
        trigger="1350.00",
        condition=TriggerCondition.LTE,
        action=OrderSide.SELL,
    )

    cancelled = await AutomaticOrderService(session).cancel(stop.id)
    assert cancelled.status is AutomaticOrderStatus.CANCELLED
    assert cancelled.cancelled_at is not None

    assert await _monitor().on_price(market_price=D("1300.00")) == []


async def test_cannot_cancel_a_triggered_order(session: AsyncSession):
    await _wallet(session)
    await _open_long(session)
    stop = await _stop_loss(
        session,
        trigger="1350.00",
        condition=TriggerCondition.LTE,
        action=OrderSide.SELL,
    )
    await _monitor().on_price(market_price=D("1349.00"))

    with pytest.raises(InvalidAutomaticOrderError, match="no longer be cancelled"):
        await AutomaticOrderService(session).cancel(stop.id)


async def test_get_unknown_id_raises(session: AsyncSession):
    with pytest.raises(AutomaticOrderNotFoundError):
        await AutomaticOrderService(session).get(9999)


# ==========================================================================
# Persistence across a restart
# ==========================================================================


async def test_active_orders_survive_a_restart(session: AsyncSession):
    """Read back through a brand-new engine -- what a restart looks like."""
    await _wallet(session)
    await _open_long(session)
    stop = await _stop_loss(
        session,
        trigger="1350.00",
        condition=TriggerCondition.LTE,
        action=OrderSide.SELL,
    )
    stop_id = stop.id

    fresh_engine = create_async_engine(settings.DATABASE_URL, poolclass=NullPool)
    try:
        maker = async_sessionmaker(bind=fresh_engine, expire_on_commit=False)
        async with maker() as fresh:
            reloaded = (
                await fresh.execute(
                    select(AutomaticOrder).where(AutomaticOrder.id == stop_id)
                )
            ).scalar_one()
            assert reloaded.status is AutomaticOrderStatus.ACTIVE
            assert reloaded.trigger_price == D("1350.00")
            assert reloaded.trigger_condition is TriggerCondition.LTE
            assert reloaded.action is OrderSide.SELL
            assert reloaded.quantity == 100
    finally:
        await fresh_engine.dispose()


# ==========================================================================
# API
# ==========================================================================


async def test_api_create_list_and_cancel(client: AsyncClient, session: AsyncSession):
    await _wallet(session)
    await _open_long(session, 100, "1400.00")

    created = await client.post(
        URL,
        json={
            "order_type": "STOP_LOSS",
            "trigger_price": "1350.00",
            "trigger_condition": "LTE",
            "action": "SELL",
            "quantity": 100,
        },
    )
    assert created.status_code == 201
    body = created.json()
    assert body["status"] == "ACTIVE"
    assert body["order_type"] == "STOP_LOSS"
    order_id = body["id"]

    active = await client.get(f"{URL}/active")
    assert active.status_code == 200
    assert [row["id"] for row in active.json()] == [order_id]

    one = await client.get(f"{URL}/{order_id}")
    assert one.status_code == 200
    assert one.json()["trigger_price"] == "1350.00"

    cancelled = await client.post(f"{URL}/{order_id}/cancel")
    assert cancelled.status_code == 200
    assert cancelled.json()["status"] == "CANCELLED"

    assert (await client.get(f"{URL}/active")).json() == []
    history = await client.get(URL)
    assert history.json()[0]["status"] == "CANCELLED"


async def test_api_rejects_an_invalid_stop_loss(client: AsyncClient, session: AsyncSession):
    await _wallet(session)
    await _open_long(session, 100, "1400.00")

    response = await client.post(
        URL,
        json={
            "order_type": "STOP_LOSS",
            "trigger_price": "1450.00",
            "trigger_condition": "GTE",
            "action": "SELL",
            "quantity": 100,
        },
    )
    assert response.status_code == 400
    assert response.json()["error"]["code"] == "invalid_automatic_order"


async def test_api_rejects_schema_violations(client: AsyncClient):
    response = await client.post(
        URL,
        json={
            "order_type": "STOP_LOSS",
            "trigger_price": "-1",
            "trigger_condition": "LTE",
            "action": "SELL",
            "quantity": 0,
        },
    )
    assert response.status_code == 422


async def test_api_unknown_id_is_404(client: AsyncClient):
    response = await client.get(f"{URL}/424242")
    assert response.status_code == 404
    assert response.json()["error"]["code"] == "automatic_order_not_found"


async def test_api_history_filters_by_status(client: AsyncClient, session: AsyncSession):
    await _wallet(session)
    await _open_long(session, 100, "1400.00")
    stop = await _stop_loss(
        session,
        trigger="1350.00",
        condition=TriggerCondition.LTE,
        action=OrderSide.SELL,
    )
    await _monitor().on_price(market_price=D("1349.00"))

    triggered = await client.get(f"{URL}?status=TRIGGERED")
    assert [row["id"] for row in triggered.json()] == [stop.id]
    assert (await client.get(f"{URL}?status=ACTIVE")).json() == []
