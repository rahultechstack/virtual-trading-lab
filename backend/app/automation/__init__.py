"""Automatic orders: stop-losses and price triggers.

    price tick -> evaluator -> monitor -> TradingEngine -> position/wallet/P&L

The monitor decides *whether* to fire; the ordinary trading engine performs the
trade. There is no second execution path.
"""

from app.automation.evaluator import (
    closing_side_for,
    condition_is_met,
    protects_position,
    stop_loss_condition_for,
)
from app.automation.monitor import (
    AutomaticOrderMonitor,
    get_automatic_order_monitor,
    reset_automatic_order_monitor,
)
from app.automation.service import AutomaticOrderService

__all__ = [
    "AutomaticOrderMonitor",
    "AutomaticOrderService",
    "closing_side_for",
    "condition_is_met",
    "get_automatic_order_monitor",
    "protects_position",
    "reset_automatic_order_monitor",
    "stop_loss_condition_for",
]
