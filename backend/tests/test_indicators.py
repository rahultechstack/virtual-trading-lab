"""Indicator tests.

Pure computation over synthetic candles -- no database, no network, no
provider. Expected values are either hand-computed or derived from a defining
identity (Bollinger's middle band *is* the SMA; MACD's histogram *is* the
difference of the other two), which catches a wrong parameter order that a
plausible-looking number would not.
"""

from datetime import UTC, datetime, timedelta
from decimal import Decimal

import pytest

from app.indicators.definitions import (
    IndicatorType,
    InvalidIndicatorError,
    Pane,
    SeriesStyle,
    parse_spec,
    parse_specs,
)
from app.indicators.library import warmup_for
from app.indicators.service import IndicatorService, candles_to_frame
from app.schemas.market_data import Candle

D = Decimal
SERVICE = IndicatorService()


def make_candles(
    closes: list[float],
    *,
    volumes: list[int] | None = None,
    start: datetime | None = None,
    step: timedelta = timedelta(days=1),
    spread: float = 1.0,
) -> list[Candle]:
    """Build a candle series from a list of closes."""
    begin = start or datetime(2026, 1, 1, tzinfo=UTC)
    candles: list[Candle] = []
    for index, close in enumerate(closes):
        candles.append(
            Candle(
                timestamp=begin + step * index,
                open=D(str(close)),
                high=D(str(close + spread)),
                low=D(str(close - spread)),
                close=D(str(close)),
                volume=(volumes[index] if volumes else 1000),
            )
        )
    return candles


def values_of(result, series_index: int = 0) -> list[Decimal]:
    return [point.value for point in result.series[series_index].points]


def compute(closes, spec_string, *, interval="1d", **kwargs):
    candles = make_candles(closes, **kwargs)
    specs = parse_specs(spec_string)
    return SERVICE.calculate(candles=candles, specs=specs, interval=interval)[0]


# ==========================================================================
# Spec parsing
# ==========================================================================


def test_defaults_are_applied_when_parameters_are_omitted():
    spec = parse_spec("sma")

    assert spec.type is IndicatorType.SMA
    assert spec.param("period") == 20
    assert spec.key == "sma_20"
    assert spec.label == "SMA(20)"


def test_parameters_override_defaults():
    spec = parse_spec("sma:50")

    assert spec.param("period") == 50
    assert spec.key == "sma_50"


def test_multi_parameter_specs():
    spec = parse_spec("macd:8:17:9")

    assert spec.as_dict() == {"fast": 8, "slow": 17, "signal": 9}
    assert spec.key == "macd_8_17_9"


def test_partial_parameters_fall_back_for_the_rest():
    spec = parse_spec("macd:8")

    assert spec.as_dict() == {"fast": 8, "slow": 26, "signal": 9}


def test_decimal_parameters():
    spec = parse_spec("bbands:20:2.5")

    assert spec.as_dict() == {"period": 20, "stddev": 2.5}
    assert spec.key == "bbands_20_2.5"


def test_unknown_indicator_is_rejected_with_the_available_list():
    with pytest.raises(InvalidIndicatorError, match="Available"):
        parse_spec("supertrend:10")


def test_a_non_numeric_parameter_is_rejected():
    with pytest.raises(InvalidIndicatorError, match="whole number"):
        parse_spec("sma:twenty")


@pytest.mark.parametrize("spec_string", ["sma:1", "sma:9999", "rsi:0"])
def test_out_of_range_parameters_are_rejected(spec_string):
    with pytest.raises(InvalidIndicatorError, match="between"):
        parse_spec(spec_string)


def test_too_many_parameters_are_rejected():
    with pytest.raises(InvalidIndicatorError, match="at most"):
        parse_spec("sma:20:30")


def test_macd_fast_must_be_shorter_than_slow():
    """A cross-parameter rule a range check alone would not catch."""
    with pytest.raises(InvalidIndicatorError, match="shorter than"):
        parse_spec("macd:26:12:9")


def test_a_list_of_specs_is_parsed_in_order():
    specs = parse_specs("sma:20,ema:21,rsi:14")

    assert [spec.key for spec in specs] == ["sma_20", "ema_21", "rsi_14"]


def test_duplicate_specs_are_computed_once():
    specs = parse_specs("sma:20,sma:20")

    assert len(specs) == 1


def test_an_empty_request_yields_nothing():
    assert parse_specs("") == []
    assert parse_specs(None) == []


def test_too_many_indicators_are_rejected():
    request = ",".join(f"sma:{period}" for period in range(10, 40))

    with pytest.raises(InvalidIndicatorError, match="At most"):
        parse_specs(request)


# ==========================================================================
# SMA
# ==========================================================================


def test_sma_matches_a_hand_computed_average():
    """Closes 1..5, period 3 -> 2, 3, 4."""
    result = compute([1, 2, 3, 4, 5], "sma:3")

    assert values_of(result) == [D("2"), D("3"), D("4")]


def test_sma_skips_its_warmup_rather_than_padding():
    result = compute([1, 2, 3, 4, 5], "sma:3")

    assert result.warmup == 2
    assert len(values_of(result)) == 3, "5 closes minus 2 warm-up bars"


def test_sma_of_a_flat_series_is_that_value():
    result = compute([100.0] * 10, "sma:5")

    assert all(value == D("100") for value in values_of(result))


def test_sma_overlays_the_price_pane():
    result = compute([1, 2, 3, 4, 5], "sma:3")

    assert result.pane is Pane.PRICE
    assert result.series[0].style is SeriesStyle.LINE


# ==========================================================================
# EMA
# ==========================================================================


def test_ema_matches_the_recurrence():
    """TA-Lib seeds the EMA with the SMA of the first `period` closes.

    Closes 1..5, period 3: seed = mean(1,2,3) = 2, multiplier = 2/4 = 0.5.
    Then 2 + (4-2)*0.5 = 3, and 3 + (5-3)*0.5 = 4.
    """
    result = compute([1, 2, 3, 4, 5], "ema:3")

    assert values_of(result) == [D("2"), D("3"), D("4")]


def test_ema_reacts_faster_than_sma():
    """After a step up, the EMA should sit above the SMA."""
    closes = [100.0] * 20 + [120.0] * 5
    ema_result = compute(closes, "ema:10")
    sma_result = compute(closes, "sma:10")

    assert values_of(ema_result)[-1] > values_of(sma_result)[-1]


# ==========================================================================
# RSI
# ==========================================================================


def test_rsi_of_an_uninterrupted_rise_is_one_hundred():
    result = compute([float(x) for x in range(1, 40)], "rsi:14")

    assert values_of(result)[-1] == D("100")


def test_rsi_of_an_uninterrupted_fall_is_zero():
    result = compute([float(x) for x in range(40, 1, -1)], "rsi:14")

    assert values_of(result)[-1] == D("0")


def test_rsi_stays_within_its_bounds():
    closes = [100 + (index % 7) * 3 - (index % 5) * 2 for index in range(60)]
    result = compute([float(c) for c in closes], "rsi:14")

    assert all(D("0") <= value <= D("100") for value in values_of(result))


def test_rsi_needs_its_own_pane_with_a_fixed_scale():
    result = compute([float(x) for x in range(1, 40)], "rsi:14")

    assert result.pane is Pane.SEPARATE
    assert result.scale_min == D("0")
    assert result.scale_max == D("100")


# ==========================================================================
# MACD
# ==========================================================================


def test_macd_returns_three_series():
    closes = [100 + index * 0.5 for index in range(80)]
    result = compute(closes, "macd:12:26:9")

    labels = [series.label for series in result.series]
    assert labels == ["MACD", "Signal", "Histogram"]


def test_the_histogram_is_the_gap_between_macd_and_signal():
    """A defining identity -- it catches a swapped parameter order."""
    closes = [100 + (index % 11) * 2 for index in range(90)]
    result = compute(closes, "macd:12:26:9")

    macd_line, signal, histogram = (values_of(result, i) for i in range(3))
    for line_value, signal_value, histogram_value in zip(macd_line, signal, histogram):
        assert abs((line_value - signal_value) - histogram_value) <= D("0.0002")


def test_macd_is_positive_in_an_uptrend():
    closes = [100 + index * 2.0 for index in range(90)]
    result = compute(closes, "macd:12:26:9")

    assert values_of(result)[-1] > 0


def test_macd_is_negative_in_a_downtrend():
    closes = [300 - index * 2.0 for index in range(90)]
    result = compute(closes, "macd:12:26:9")

    assert values_of(result)[-1] < 0


def test_the_histogram_draws_as_a_histogram():
    closes = [100 + index * 0.5 for index in range(80)]
    result = compute(closes, "macd:12:26:9")

    assert result.series[2].style is SeriesStyle.HISTOGRAM
    assert result.series[0].style is SeriesStyle.LINE


# ==========================================================================
# Bollinger Bands
# ==========================================================================


def test_the_middle_band_is_the_simple_moving_average():
    """Another defining identity."""
    closes = [100 + (index % 9) * 3.0 for index in range(50)]
    bands = compute(closes, "bbands:20:2")
    sma = compute(closes, "sma:20")

    assert values_of(bands, 1) == values_of(sma)


def test_the_bands_are_symmetric_about_the_middle():
    closes = [100 + (index % 9) * 3.0 for index in range(50)]
    result = compute(closes, "bbands:20:2")

    upper, middle, lower = (values_of(result, i) for i in range(3))
    for up, mid, low in zip(upper, middle, lower):
        assert abs((up - mid) - (mid - low)) <= D("0.0002")


def test_a_flat_series_collapses_the_bands_onto_the_average():
    """Zero standard deviation means no envelope."""
    result = compute([100.0] * 40, "bbands:20:2")

    upper, middle, lower = (values_of(result, i) for i in range(3))
    assert upper[-1] == middle[-1] == lower[-1] == D("100")


def test_a_wider_deviation_gives_wider_bands():
    closes = [100 + (index % 9) * 3.0 for index in range(50)]
    narrow = compute(closes, "bbands:20:1")
    wide = compute(closes, "bbands:20:3")

    narrow_width = values_of(narrow, 0)[-1] - values_of(narrow, 2)[-1]
    wide_width = values_of(wide, 0)[-1] - values_of(wide, 2)[-1]
    assert wide_width > narrow_width


# ==========================================================================
# VWAP
# ==========================================================================


def test_vwap_of_a_single_bar_is_its_typical_price():
    """(high + low + close) / 3 with high/low one either side of close."""
    result = compute([100.0], "vwap:20", spread=3.0)

    assert values_of(result) == [D("100")]


def test_vwap_is_volume_weighted_not_a_plain_average():
    """Two bars, the second carrying nine times the volume.

    Typical prices 100 and 200, so a plain mean would be 150; weighted by
    1,000 and 9,000 it must land at 190.
    """
    candles = make_candles([100.0, 200.0], volumes=[1000, 9000], spread=0.0)
    result = SERVICE.calculate(
        candles=candles, specs=parse_specs("vwap:20"), interval="1d"
    )[0]

    assert values_of(result)[-1] == D("190")


def test_vwap_anchors_to_the_session_on_intraday_intervals():
    """The first bar of a new day restarts the accumulation.

    Two bars a day at 10:00 and 11:00 IST. The second day's first bar must
    equal its own typical price, not carry the first day's average forward.
    """
    start = datetime(2026, 1, 1, 4, 30, tzinfo=UTC)  # 10:00 IST
    candles = [
        *make_candles([100.0, 110.0], start=start, step=timedelta(hours=1), spread=0.0),
        *make_candles(
            [500.0, 510.0],
            start=start + timedelta(days=1),
            step=timedelta(hours=1),
            spread=0.0,
        ),
    ]

    result = SERVICE.calculate(
        candles=candles, specs=parse_specs("vwap"), interval="1h"
    )[0]
    values = values_of(result)

    assert values[0] == D("100")
    assert values[1] == D("105"), "averaged within the first session"
    assert values[2] == D("500"), "the new session restarts the anchor"


def test_vwap_rolls_rather_than_anchoring_on_daily_intervals():
    """Each daily bar is its own session, so anchoring would be meaningless."""
    candles = make_candles([100.0, 200.0, 300.0], spread=0.0)

    result = SERVICE.calculate(
        candles=candles, specs=parse_specs("vwap:3"), interval="1d"
    )[0]

    assert values_of(result)[-1] == D("200"), "mean of the 3-bar window"


def test_vwap_has_no_warmup():
    result = compute([100.0, 101.0, 102.0], "vwap:20")

    assert result.warmup == 0
    assert len(values_of(result)) == 3


def test_zero_volume_bars_do_not_divide_by_zero():
    candles = make_candles([100.0, 110.0], volumes=[0, 0], spread=0.0)

    result = SERVICE.calculate(
        candles=candles, specs=parse_specs("vwap:20"), interval="1d"
    )[0]

    assert result.series[0].points == [], "no volume means no meaningful VWAP"


# ==========================================================================
# Insufficient data
# ==========================================================================


def test_a_window_shorter_than_the_warmup_is_flagged_not_hidden():
    result = compute([1, 2, 3], "sma:20")

    assert result.insufficient_data is True
    assert result.series[0].points == []
    assert result.warmup == 19


def test_no_candles_at_all_still_returns_the_requested_indicator():
    results = SERVICE.calculate(
        candles=[], specs=parse_specs("sma:20,rsi:14"), interval="1d"
    )

    assert len(results) == 2
    assert all(result.insufficient_data for result in results)


def test_a_sufficient_window_is_not_flagged():
    result = compute([float(x) for x in range(30)], "sma:20")

    assert result.insufficient_data is False


@pytest.mark.parametrize(
    ("spec_string", "expected"),
    [("sma:20", 19), ("ema:21", 20), ("rsi:14", 14), ("macd:12:26:9", 33), ("vwap", 0)],
)
def test_warmup_lengths(spec_string, expected):
    assert warmup_for(parse_spec(spec_string)) == expected


# ==========================================================================
# Frame construction and ordering
# ==========================================================================


def test_the_frame_preserves_candle_order_and_values():
    candles = make_candles([100.0, 101.0, 102.0])

    frame = candles_to_frame(candles, "1d")

    assert list(frame["close"]) == [100.0, 101.0, 102.0]
    assert frame.index.is_monotonic_increasing
    assert frame.attrs["interval"] == "1d"


def test_points_are_aligned_to_their_candle_timestamps():
    candles = make_candles([1, 2, 3, 4, 5])

    result = SERVICE.calculate(
        candles=candles, specs=parse_specs("sma:3"), interval="1d"
    )[0]

    # The first two bars are warm-up, so values start at the third candle.
    assert [point.timestamp for point in result.series[0].points] == [
        candle.timestamp for candle in candles[2:]
    ]


def test_indicators_are_returned_in_the_order_requested():
    candles = make_candles([float(x) for x in range(60)])

    results = SERVICE.calculate(
        candles=candles, specs=parse_specs("rsi:14,sma:20,vwap"), interval="1d"
    )

    assert [result.key for result in results] == ["rsi_14", "sma_20", "vwap_20"]


def test_no_signal_or_recommendation_is_produced():
    """This stage computes values only -- interpretation comes later."""
    candles = make_candles([float(x) for x in range(60)])

    result = SERVICE.calculate(
        candles=candles, specs=parse_specs("rsi:14"), interval="1d"
    )[0]

    fields = vars(result).keys()
    for banned in ("signal", "recommendation", "action", "verdict"):
        assert banned not in fields
