"""Portfolio history and performance contracts."""

from datetime import datetime
from decimal import Decimal

from pydantic import BaseModel, ConfigDict, Field

from app.schemas.common import Quantity

from app.models.portfolio_snapshot import SnapshotSource


class SnapshotResponse(BaseModel):
    """One point on the equity curve."""

    model_config = ConfigDict(from_attributes=True)

    id: int
    captured_at: datetime
    source: SnapshotSource
    symbol: str

    quantity: Quantity
    average_price: Decimal
    mark_price: Decimal | None = Field(
        default=None, description="Price the position was valued at. Null when flat."
    )

    cash: Decimal
    position_value: Decimal = Field(description="Signed; negative for a short.")
    total_value: Decimal = Field(description="cash + position_value.")

    realized_pnl: Decimal = Field(description="Cumulative gross, before charges.")
    total_charges: Decimal
    unrealized_pnl: Decimal
    net_pnl: Decimal = Field(description="Net realized plus unrealized.")


class SnapshotSeriesResponse(BaseModel):
    """Snapshots oldest first, ready to plot."""

    count: int
    first_captured_at: datetime | None
    last_captured_at: datetime | None
    snapshots: list[SnapshotResponse]


class TradeExtremeResponse(BaseModel):
    """The single best or worst closing trade."""

    model_config = ConfigDict(from_attributes=True)

    trade_id: int
    side: str
    quantity: Quantity
    execution_price: Decimal
    gross_pnl: Decimal
    total_charges: Decimal
    net_pnl: Decimal
    created_at: datetime


class PerformanceResponse(BaseModel):
    """Aggregate trading performance.

    Wins and losses are judged over *closing* fills only, on **net** P&L --
    an opening fill realizes nothing, and a trade that is gross-positive but
    net-negative is a loss.
    """

    model_config = ConfigDict(from_attributes=True)

    total_trades: int
    closing_trades: int
    winning_trades: int
    losing_trades: int
    breakeven_trades: int
    win_rate: Decimal | None = Field(
        default=None, description="Percentage of closing trades that were net-positive."
    )

    total_gross_pnl: Decimal
    total_charges: Decimal
    total_net_pnl: Decimal

    average_win: Decimal | None = None
    average_loss: Decimal | None = None
    profit_factor: Decimal | None = Field(
        default=None, description="Gross profit divided by gross loss."
    )

    largest_winning_trade: TradeExtremeResponse | None = None
    largest_losing_trade: TradeExtremeResponse | None = None

    total_orders: int
    filled_orders: int
    rejected_orders: int
