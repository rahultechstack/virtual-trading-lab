"""The virtual trading engine.

    TradingEngine
      |-- OrderManager
      |-- ExecutionEngine
      |-- PositionManager
      |-- PortfolioManager
      +-- PnLCalculator

Depends on neither the web layer nor any market-data provider.
"""

from app.trading.engine import OrderResult, TradingEngine
from app.trading.execution import ExecutionEngine, Fill
from app.trading.order_manager import OrderManager
from app.trading.pnl import PnLCalculator
from app.trading.portfolio import PortfolioManager, PortfolioSnapshot
from app.trading.position_manager import FillOutcome, PositionManager, apply_fill

__all__ = [
    "ExecutionEngine",
    "Fill",
    "FillOutcome",
    "OrderManager",
    "OrderResult",
    "PnLCalculator",
    "PortfolioManager",
    "PortfolioSnapshot",
    "PositionManager",
    "TradingEngine",
    "apply_fill",
]
