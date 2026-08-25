"""Backtesting.

    candles -> indicators -> strategy -> sizing -> execution -> portfolio

Uses the live trading system's own execution pricing and position accounting,
so a backtest is comparable to real trading rather than merely similar to it.
"""

from app.backtest.engine import (
    BacktestConfig,
    BacktestEngine,
    FillTiming,
    PositionSizer,
    SizingMode,
)
from app.backtest.portfolio import (
    BacktestPortfolio,
    BacktestTrade,
    EquityPoint,
    InsufficientCash,
)
from app.backtest.results import BacktestResult, max_drawdown, summarise

__all__ = [
    "BacktestConfig",
    "BacktestEngine",
    "BacktestPortfolio",
    "BacktestResult",
    "BacktestTrade",
    "EquityPoint",
    "FillTiming",
    "InsufficientCash",
    "PositionSizer",
    "SizingMode",
    "max_drawdown",
    "summarise",
]
