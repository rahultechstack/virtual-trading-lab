"""Indicator API contracts."""

from datetime import datetime
from decimal import Decimal

from pydantic import BaseModel, ConfigDict, Field

from app.indicators.definitions import IndicatorType, Pane, SeriesStyle
from app.schemas.market_data import Interval


class IndicatorPointResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    timestamp: datetime
    value: Decimal


class IndicatorSeriesResponse(BaseModel):
    """One plottable line."""

    model_config = ConfigDict(from_attributes=True)

    key: str
    label: str
    style: SeriesStyle
    points: list[IndicatorPointResponse]


class IndicatorResponse(BaseModel):
    """One computed indicator.

    ``pane`` says where it belongs: ``price`` overlays the candles, ``separate``
    needs its own axis below them.
    """

    model_config = ConfigDict(from_attributes=True)

    key: str
    type: IndicatorType
    label: str
    pane: Pane
    params: dict[str, float | int]
    warmup: int = Field(
        description="Leading bars with no value while the indicator warms up."
    )
    insufficient_data: bool = Field(
        description="True when the candle window was too short to produce anything."
    )
    scale_min: Decimal | None = None
    scale_max: Decimal | None = None
    series: list[IndicatorSeriesResponse]


class IndicatorSetResponse(BaseModel):
    """Indicators computed over one candle window."""

    symbol: str
    exchange: str
    interval: Interval
    provider: str
    candle_count: int
    indicators: list[IndicatorResponse]


class IndicatorParamCatalogue(BaseModel):
    name: str
    default: float | int
    minimum: float | int
    maximum: float | int


class IndicatorCatalogueEntry(BaseModel):
    type: str
    display_name: str
    pane: str
    description: str
    params: list[IndicatorParamCatalogue]
