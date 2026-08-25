"""Indicator calculations.

TA-Lib does the standard studies; VWAP is computed here because TA-Lib does
not provide it.

Every function takes the OHLCV frame and returns ``{series_key: ndarray}``
aligned index-for-index with the input. Warm-up periods come back as ``NaN``
and are dropped later rather than back-filled -- a moving average that does
not exist yet must not be drawn as if it did.
"""

from collections.abc import Callable
from decimal import Decimal

import numpy as np
import pandas as pd
import talib

from app.indicators.definitions import IndicatorSpec, IndicatorType

#: Intervals where VWAP anchors to the trading session.
INTRADAY_INTERVALS = frozenset({"1m", "5m", "15m", "30m", "1h"})

#: Exchange timezone, which is what defines a session boundary.
SESSION_TIMEZONE = "Asia/Kolkata"


def _close(frame: pd.DataFrame) -> np.ndarray:
    return frame["close"].to_numpy(dtype=np.float64)


def sma(frame: pd.DataFrame, spec: IndicatorSpec) -> dict[str, np.ndarray]:
    period = int(spec.param("period"))
    return {spec.key: talib.SMA(_close(frame), timeperiod=period)}


def ema(frame: pd.DataFrame, spec: IndicatorSpec) -> dict[str, np.ndarray]:
    period = int(spec.param("period"))
    return {spec.key: talib.EMA(_close(frame), timeperiod=period)}


def rsi(frame: pd.DataFrame, spec: IndicatorSpec) -> dict[str, np.ndarray]:
    period = int(spec.param("period"))
    return {spec.key: talib.RSI(_close(frame), timeperiod=period)}


def macd(frame: pd.DataFrame, spec: IndicatorSpec) -> dict[str, np.ndarray]:
    fast = int(spec.param("fast"))
    slow = int(spec.param("slow"))
    signal = int(spec.param("signal"))

    line, signal_line, histogram = talib.MACD(
        _close(frame), fastperiod=fast, slowperiod=slow, signalperiod=signal
    )
    return {
        f"{spec.key}_macd": line,
        f"{spec.key}_signal": signal_line,
        f"{spec.key}_histogram": histogram,
    }


def bbands(frame: pd.DataFrame, spec: IndicatorSpec) -> dict[str, np.ndarray]:
    period = int(spec.param("period"))
    deviations = float(spec.param("stddev"))

    upper, middle, lower = talib.BBANDS(
        _close(frame),
        timeperiod=period,
        nbdevup=deviations,
        nbdevdn=deviations,
        matype=talib.MA_Type.SMA,
    )
    return {
        f"{spec.key}_upper": upper,
        f"{spec.key}_middle": middle,
        f"{spec.key}_lower": lower,
    }


def vwap(frame: pd.DataFrame, spec: IndicatorSpec) -> dict[str, np.ndarray]:
    """Volume Weighted Average Price.

    TA-Lib has no VWAP, so it is computed here from the typical price
    ``(high + low + close) / 3`` weighted by volume.

    Two modes, chosen from the interval:

    * **Intraday** -- anchored to the trading session, resetting at each new
      exchange-local day. This is the conventional VWAP.
    * **Daily and above** -- a rolling window of ``period`` bars. A session
      anchor is meaningless when each bar *is* a session: it would just
      reproduce the typical price of every bar.

    Bars with zero volume contribute nothing and inherit the running value
    rather than producing a divide-by-zero.
    """
    typical = (frame["high"] + frame["low"] + frame["close"]) / 3.0
    volume = frame["volume"].astype("float64")
    weighted = typical * volume

    interval = str(frame.attrs.get("interval", "1d"))

    if interval in INTRADAY_INTERVALS:
        # Group by exchange-local calendar day so the anchor matches the
        # session, not UTC midnight.
        sessions = frame.index.tz_convert(SESSION_TIMEZONE).normalize()
        cumulative_weighted = weighted.groupby(sessions).cumsum()
        cumulative_volume = volume.groupby(sessions).cumsum()
    else:
        period = int(spec.param("period"))
        window = min(period, len(frame)) or 1
        cumulative_weighted = weighted.rolling(window=window, min_periods=1).sum()
        cumulative_volume = volume.rolling(window=window, min_periods=1).sum()

    values = np.where(
        cumulative_volume.to_numpy() > 0,
        cumulative_weighted.to_numpy()
        / np.where(cumulative_volume.to_numpy() > 0, cumulative_volume.to_numpy(), 1.0),
        np.nan,
    )
    return {spec.key: values}


#: Dispatch table. Adding an indicator means one entry here and one in the
#: catalogue -- nothing else changes.
CALCULATORS: dict[
    IndicatorType, Callable[[pd.DataFrame, IndicatorSpec], dict[str, np.ndarray]]
] = {
    IndicatorType.SMA: sma,
    IndicatorType.EMA: ema,
    IndicatorType.RSI: rsi,
    IndicatorType.MACD: macd,
    IndicatorType.BBANDS: bbands,
    IndicatorType.VWAP: vwap,
}


def warmup_for(spec: IndicatorSpec) -> int:
    """How many leading bars an indicator cannot produce a value for.

    Used to warn a caller who asked for fewer candles than the indicator
    needs, rather than silently returning an empty series.
    """
    if spec.type in (IndicatorType.SMA, IndicatorType.EMA, IndicatorType.BBANDS):
        return int(spec.param("period")) - 1
    if spec.type is IndicatorType.RSI:
        return int(spec.param("period"))
    if spec.type is IndicatorType.MACD:
        return int(spec.param("slow")) + int(spec.param("signal")) - 2
    return 0


def to_decimal(value: float) -> Decimal | None:
    """Quantise an indicator value for the wire, or None where it is NaN."""
    if value is None or not np.isfinite(value):
        return None
    return Decimal(str(round(float(value), 4)))
