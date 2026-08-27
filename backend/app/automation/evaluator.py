"""Trigger evaluation.

Pure functions over ``Decimal`` -- no database, no session, no ORM object. The
question "should this fire?" is answered here and nowhere else, so it can be
tested exhaustively without a market, and so the frontend never has to answer
it.

Boundaries are **inclusive**, matching the brief: ``>= 1450`` fires at exactly
1450, ``<= 1350`` fires at exactly 1350.
"""

from decimal import Decimal

from app.models.automatic_order import TriggerCondition
from app.models.enums import OrderSide


def condition_is_met(
    *,
    condition: TriggerCondition,
    trigger_price: Decimal,
    market_price: Decimal,
) -> bool:
    """Whether ``market_price`` satisfies the trigger.

    Args:
        condition: GTE fires at or above the trigger, LTE at or below it.
        trigger_price: The configured level.
        market_price: The latest observed price.
    """
    if condition is TriggerCondition.GTE:
        return market_price >= trigger_price
    return market_price <= trigger_price


def closing_side_for(position_quantity: Decimal) -> OrderSide | None:
    """The side that reduces a position, or ``None`` when flat.

    A long is closed by SELL, a short by BUY_TO_COVER -- the two closing-only
    sides the engine already enforces.
    """
    if position_quantity > 0:
        return OrderSide.SELL
    if position_quantity < 0:
        return OrderSide.BUY_TO_COVER
    return None


def stop_loss_condition_for(position_quantity: Decimal) -> TriggerCondition | None:
    """The only condition that makes sense as a stop on this position.

    A long is stopped out on the way **down** (LTE); a short on the way **up**
    (GTE). Anything else is not a stop-loss, it is a take-profit -- which is
    what a PRICE_TRIGGER is for.
    """
    if position_quantity > 0:
        return TriggerCondition.LTE
    if position_quantity < 0:
        return TriggerCondition.GTE
    return None


def protects_position(action: OrderSide, position_quantity: Decimal) -> bool:
    """Whether ``action`` still reduces the position it was created against.

    Used to retire a stop-loss whose position has gone flat or reversed --
    a SELL stop is meaningless once the long is gone.
    """
    expected = closing_side_for(position_quantity)
    return expected is not None and action is expected
