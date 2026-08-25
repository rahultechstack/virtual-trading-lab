"""The virtual trading engine.

    TradingEngine
      |-- OrderManager
      |-- ExecutionEngine     composes the three cost models below
      |     |-- SpreadModel
      |     |-- SlippageModel
      |     +-- FeeCalculator
      |-- PositionManager
      |-- PortfolioManager
      +-- PnLCalculator

Depends on neither the web layer nor any market-data provider.
"""

from app.trading.engine import OrderResult, TradingEngine
from app.trading.execution import ExecutionEngine, Fill
from app.trading.fees import ChargeBreakdown, FeeCalculator, Segment
from app.trading.order_manager import OrderManager
from app.trading.pnl import PnLCalculator
from app.trading.portfolio import PortfolioManager, PortfolioSnapshot
from app.trading.position_manager import FillOutcome, PositionManager, apply_fill
from app.trading.slippage import SlippageModel, SlippageResult, SlippageType
from app.trading.spread import BidAsk, SpreadModel, SpreadResult

__all__ = [
    "BidAsk",
    "ChargeBreakdown",
    "ExecutionEngine",
    "FeeCalculator",
    "Fill",
    "FillOutcome",
    "OrderManager",
    "OrderResult",
    "PnLCalculator",
    "PortfolioManager",
    "PortfolioSnapshot",
    "PositionManager",
    "Segment",
    "SlippageModel",
    "SlippageResult",
    "SlippageType",
    "SpreadModel",
    "SpreadResult",
    "TradingEngine",
    "apply_fill",
]
