"""Strategies.

A strategy sees market data and returns BUY, SELL, SHORT, COVER or HOLD. It
knows nothing about the wallet, the database or the web layer.
"""

from app.strategies.base import (
    Decision,
    Signal,
    Strategy,
    StrategyContext,
    StrategyParam,
)
from app.strategies.ma_crossover import MovingAverageCrossover
from app.strategies.registry import (
    InvalidStrategyParamsError,
    UnknownStrategyError,
    available_strategies,
    create_strategy,
    describe_all,
)

__all__ = [
    "Decision",
    "InvalidStrategyParamsError",
    "MovingAverageCrossover",
    "Signal",
    "Strategy",
    "StrategyContext",
    "StrategyParam",
    "UnknownStrategyError",
    "available_strategies",
    "create_strategy",
    "describe_all",
]
