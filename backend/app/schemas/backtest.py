"""Strategy and backtest API contracts."""

from datetime import datetime
from decimal import Decimal
from typing import Any

from pydantic import BaseModel, ConfigDict, Field

from app.schemas.common import Quantity

from app.backtest.engine import FillTiming, SizingMode
from app.core.config import settings
from app.models.enums import OrderSide
from app.schemas.market_data import Interval


class StrategyParamSchema(BaseModel):
    name: str
    default: float | int
    minimum: float | int
    maximum: float | int
    description: str = ""


class StrategySchema(BaseModel):
    name: str
    display_name: str
    description: str
    params: list[StrategyParamSchema]


class BacktestRequest(BaseModel):
    """A backtest to run."""

    strategy: str = Field(description="Strategy name, e.g. 'ma_crossover'.")
    params: dict[str, Any] = Field(
        default_factory=dict, description="Strategy parameters; defaults fill the rest."
    )

    symbol: str | None = Field(
        default=None,
        description="Instrument to backtest. Defaults to the configured default.",
    )
    interval: Interval = Interval.ONE_DAY
    limit: int = Field(
        default=500,
        ge=10,
        le=settings.MAX_CANDLES_PER_REQUEST,
        description="Candles to run over.",
    )
    start: datetime | None = None
    end: datetime | None = None

    initial_capital: Decimal = Field(
        default=Decimal("1000000.00"), gt=0, max_digits=18, decimal_places=2
    )
    fill_timing: FillTiming = Field(
        default=FillTiming.NEXT_OPEN,
        description=(
            "next_open fills against the bar after the signal, which is the "
            "first tradable price. current_close uses the bar that produced "
            "the signal, which was not knowable at that moment - lookahead."
        ),
    )
    sizing_mode: SizingMode = SizingMode.PERCENT_OF_EQUITY
    equity_percent: Decimal = Field(default=Decimal("95"), gt=0, le=100)
    fixed_quantity: Decimal = Field(
        default=Decimal("100"),
        gt=0,
        le=settings.MAX_ORDER_QUANTITY,
        max_digits=28,
        decimal_places=8,
        description=(
            "Used by FIXED_QUANTITY sizing. Fractional for crypto; rounded "
            "down to the instrument's tradable increment."
        ),
    )
    fixed_value: Decimal = Field(
        default=Decimal("100000.00"), gt=0, max_digits=18, decimal_places=2
    )
    close_at_end: bool = Field(
        default=True, description="Flatten on the last bar so the result is realized."
    )


class BacktestTradeSchema(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    index: int
    timestamp: datetime
    side: OrderSide
    quantity: Quantity
    reference_price: Decimal
    execution_price: Decimal
    spread_cost: Decimal
    slippage_cost: Decimal
    total_charges: Decimal
    gross_pnl: Decimal
    net_pnl: Decimal
    closed_quantity: Quantity
    position_after: Quantity
    cash_after: Decimal
    reason: str


class EquityPointSchema(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    timestamp: datetime
    mark_price: Decimal
    cash: Decimal
    position: Quantity
    position_value: Decimal
    total_value: Decimal
    realized_pnl: Decimal
    unrealized_pnl: Decimal
    net_pnl: Decimal


class BacktestResultSchema(BaseModel):
    """Everything one backtest produced.

    Wins and losses count *closing* fills only, judged on net P&L -- the same
    rules the live performance summary uses.
    """

    model_config = ConfigDict(from_attributes=True)

    strategy: str
    symbol: str
    exchange: str
    asset_class: str = Field(description="STOCK or CRYPTO.")
    trading_calendar: str = Field(
        description=(
            'Calendar the instrument trades under: "nse" or "crypto". '
            "A crypto run legitimately contains weekend bars."
        )
    )
    interval: str

    start_at: datetime | None
    end_at: datetime | None
    bars: int

    initial_capital: Decimal
    final_equity: Decimal
    total_return: Decimal
    total_return_pct: Decimal

    total_trades: int
    closing_trades: int
    winning_trades: int
    losing_trades: int
    breakeven_trades: int
    win_rate: Decimal | None

    gross_pnl: Decimal
    total_charges: Decimal
    net_pnl: Decimal

    max_drawdown: Decimal
    max_drawdown_pct: Decimal
    profit_factor: Decimal | None
    average_win: Decimal | None
    average_loss: Decimal | None
    largest_win: Decimal | None
    largest_loss: Decimal | None

    exposure_pct: Decimal
    rejected_orders: int
    final_position: Quantity

    trades: list[BacktestTradeSchema]
    equity_curve: list[EquityPointSchema]
