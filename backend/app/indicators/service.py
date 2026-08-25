"""Indicator service.

Turns candles into chartable series:

    candles  ->  pandas DataFrame  ->  TA-Lib  ->  IndicatorResult

Deliberately decoupled from the market-data layer: it is handed candles rather
than fetching them, so the same service works over a live feed, a fixture or a
future backtest without changing.

It produces **values only**. No buy/sell interpretation is applied anywhere in
this module -- signal generation is a later stage.
"""

from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal

import pandas as pd

from app.core.logging import get_logger
from app.indicators.definitions import (
    CATALOGUE,
    IndicatorSpec,
    IndicatorType,
    Pane,
    SeriesStyle,
)
from app.indicators.library import CALCULATORS, to_decimal, warmup_for
from app.schemas.market_data import Candle

logger = get_logger(__name__)

#: Which sub-series of a multi-line indicator draws as a histogram.
_HISTOGRAM_SUFFIXES = ("_histogram",)

#: Friendly labels for the sub-series of multi-line indicators.
_SERIES_LABELS = {
    "_macd": "MACD",
    "_signal": "Signal",
    "_histogram": "Histogram",
    "_upper": "Upper",
    "_middle": "Middle",
    "_lower": "Lower",
}


@dataclass(frozen=True)
class IndicatorPoint:
    timestamp: datetime
    value: Decimal


@dataclass(frozen=True)
class IndicatorSeriesResult:
    """One plottable line of an indicator."""

    key: str
    label: str
    style: SeriesStyle
    points: list[IndicatorPoint]


@dataclass(frozen=True)
class IndicatorResult:
    """Everything one requested indicator produced."""

    key: str
    type: IndicatorType
    label: str
    pane: Pane
    params: dict[str, int | float]
    #: Leading bars with no value, because the indicator had not warmed up.
    warmup: int
    #: True when the candle window was too short to produce any value at all.
    insufficient_data: bool
    scale_min: Decimal | None
    scale_max: Decimal | None
    series: list[IndicatorSeriesResult]


def candles_to_frame(candles: list[Candle], interval: str) -> pd.DataFrame:
    """Build the OHLCV frame TA-Lib works on.

    Prices are ``Decimal`` on the way in and become ``float64`` here, which is
    what the C library requires. That is safe: these are statistical studies,
    not money. Cash and P&L stay in Decimal everywhere else in the system.
    """
    frame = pd.DataFrame(
        {
            "open": [float(candle.open) for candle in candles],
            "high": [float(candle.high) for candle in candles],
            "low": [float(candle.low) for candle in candles],
            "close": [float(candle.close) for candle in candles],
            "volume": [float(candle.volume) for candle in candles],
        },
        index=pd.DatetimeIndex(
            [candle.timestamp for candle in candles], name="timestamp"
        ),
    )
    # VWAP needs the interval to decide between session anchoring and a
    # rolling window.
    frame.attrs["interval"] = interval
    return frame


def _series_label(spec: IndicatorSpec, series_key: str) -> str:
    for suffix, label in _SERIES_LABELS.items():
        if series_key.endswith(suffix):
            return label
    return spec.label


def _series_style(series_key: str) -> SeriesStyle:
    if series_key.endswith(_HISTOGRAM_SUFFIXES):
        return SeriesStyle.HISTOGRAM
    return SeriesStyle.LINE


class IndicatorService:
    """Computes indicators over a candle series."""

    def calculate(
        self,
        *,
        candles: list[Candle],
        specs: list[IndicatorSpec],
        interval: str,
    ) -> list[IndicatorResult]:
        """Compute each requested indicator over ``candles``.

        Returns results in the order requested. An indicator whose warm-up
        exceeds the window is still returned, flagged ``insufficient_data``
        with an empty series, rather than omitted -- the caller asked for it
        and deserves to know why there is nothing to draw.
        """
        if not specs:
            return []
        if not candles:
            return [self._empty(spec) for spec in specs]

        frame = candles_to_frame(candles, interval)
        timestamps = [candle.timestamp for candle in candles]

        results: list[IndicatorResult] = []
        for spec in specs:
            calculator = CALCULATORS[spec.type]
            try:
                raw = calculator(frame, spec)
            except Exception as exc:  # noqa: BLE001 - one bad indicator must not
                # take down the whole request.
                logger.warning("Indicator %s failed: %s", spec.key, exc)
                results.append(self._empty(spec))
                continue

            series = [
                IndicatorSeriesResult(
                    key=series_key,
                    label=_series_label(spec, series_key),
                    style=_series_style(series_key),
                    points=self._to_points(timestamps, values),
                )
                for series_key, values in raw.items()
            ]

            produced = any(entry.points for entry in series)
            results.append(
                IndicatorResult(
                    key=spec.key,
                    type=spec.type,
                    label=spec.label,
                    pane=spec.definition.pane,
                    params=spec.as_dict(),
                    warmup=warmup_for(spec),
                    insufficient_data=not produced,
                    scale_min=spec.definition.scale_min,
                    scale_max=spec.definition.scale_max,
                    series=series,
                )
            )

        return results

    @staticmethod
    def _to_points(timestamps: list[datetime], values) -> list[IndicatorPoint]:
        """Pair values with their candle times, dropping the warm-up NaNs.

        Leading NaNs are omitted rather than sent as nulls: a moving average
        that does not exist yet should simply not be drawn.
        """
        points: list[IndicatorPoint] = []
        for timestamp, raw in zip(timestamps, values):
            value = to_decimal(raw)
            if value is None:
                continue
            points.append(IndicatorPoint(timestamp=timestamp, value=value))
        return points

    @staticmethod
    def _empty(spec: IndicatorSpec) -> IndicatorResult:
        return IndicatorResult(
            key=spec.key,
            type=spec.type,
            label=spec.label,
            pane=spec.definition.pane,
            params=spec.as_dict(),
            warmup=warmup_for(spec),
            insufficient_data=True,
            scale_min=spec.definition.scale_min,
            scale_max=spec.definition.scale_max,
            series=[],
        )

    @staticmethod
    def catalogue() -> list[dict]:
        """The available indicators and their parameters, for a UI to render."""
        return [
            {
                "type": definition.type.value,
                "display_name": definition.display_name,
                "pane": definition.pane.value,
                "description": definition.description,
                "params": [
                    {
                        "name": param.name,
                        "default": (
                            float(param.default)
                            if isinstance(param.default, Decimal)
                            else param.default
                        ),
                        "minimum": (
                            float(param.minimum)
                            if isinstance(param.minimum, Decimal)
                            else param.minimum
                        ),
                        "maximum": (
                            float(param.maximum)
                            if isinstance(param.maximum, Decimal)
                            else param.maximum
                        ),
                    }
                    for param in definition.params
                ],
            }
            for definition in CATALOGUE.values()
        ]


indicator_service = IndicatorService()
