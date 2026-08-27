"""Market calendar API contracts.

The backend resolves trading status; the frontend renders it. No React
component computes whether a market is open.
"""

from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field

from app.market_data.instruments import AssetClass
from app.markets.calendar import TradingStatus


class MarketStatusResponse(BaseModel):
    """Whether one instrument's market is open, and when it next changes."""

    model_config = ConfigDict(from_attributes=True)

    symbol: str
    asset_class: AssetClass
    market: str = Field(description='Human label, e.g. "NSE Cash Market".')
    calendar: str = Field(description='Calendar governing it: "nse" or "crypto".')
    status: TradingStatus = Field(
        description="OPEN, PRE_OPEN, CLOSED, WEEKEND or HOLIDAY."
    )
    is_open: bool = Field(description="Whether continuous trading is available now.")
    is_24x7: bool = Field(description="True for a market with no session boundaries.")
    timezone: str = Field(description="IANA zone the schedule is expressed in.")
    server_time: datetime = Field(description="The moment this describes.")
    next_open: datetime | None = Field(
        default=None,
        description="When trading next becomes available. Null for a 24/7 market.",
    )
    next_close: datetime | None = Field(
        default=None,
        description="When trading next stops. Null for a 24/7 market.",
    )
    reason: str = Field(description="Human explanation of the status.")
    enforced: bool = Field(
        description=(
            "Whether the trading engine REFUSES orders while closed "
            "(ENFORCE_MARKET_HOURS). When false the status is informational."
        )
    )
