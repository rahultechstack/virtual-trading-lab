"""Strategy framework tests.

Pure: no database, no network, no provider.
"""

from datetime import UTC, datetime, timedelta
from decimal import Decimal

import pytest

from app.models.enums import OrderSide
from app.schemas.market_data import Candle
from app.strategies.base import Decision, Signal, StrategyContext
from app.strategies.ma_crossover import MovingAverageCrossover
from app.strategies.registry import (
    InvalidStrategyParamsError,
    UnknownStrategyError,
    available_strategies,
    create_strategy,
    describe_all,
)

D = Decimal


def make_candles(closes: list[float]) -> list[Candle]:
    begin = datetime(2026, 1, 1, tzinfo=UTC)
    return [
        Candle(
            timestamp=begin + timedelta(days=index),
            open=D(str(close)),
            high=D(str(close + 1)),
            low=D(str(close - 1)),
            close=D(str(close)),
            volume=1000,
        )
        for index, close in enumerate(closes)
    ]


def context(
    *,
    index: int = 10,
    position: int = 0,
    indicators: dict[str, list] | None = None,
    candles: list[Candle] | None = None,
) -> StrategyContext:
    series = candles or make_candles([100.0] * (index + 1))
    return StrategyContext(
        index=index,
        candle=series[index],
        candles=series[: index + 1],
        position=position,
        average_price=D("100"),
        cash=D("1000000"),
        equity=D("1000000"),
        _indicators=indicators or {},
    )


# ==========================================================================
# Signals
# ==========================================================================


def test_every_signal_maps_to_the_right_order_side():
    assert Signal.BUY.order_side is OrderSide.BUY
    assert Signal.SELL.order_side is OrderSide.SELL
    assert Signal.SHORT.order_side is OrderSide.SHORT_SELL
    assert Signal.COVER.order_side is OrderSide.BUY_TO_COVER


def test_hold_maps_to_no_order():
    assert Signal.HOLD.order_side is None
    assert Signal.HOLD.is_actionable is False


def test_the_five_required_signals_exist():
    assert {signal.value for signal in Signal} == {
        "BUY",
        "SELL",
        "SHORT",
        "COVER",
        "HOLD",
    }


def test_a_hold_decision_carries_its_reason():
    decision = Decision.hold("nothing to do")

    assert decision.signal is Signal.HOLD
    assert decision.reason == "nothing to do"
    assert decision.quantity is None


# ==========================================================================
# Context: no lookahead
# ==========================================================================


def test_a_negative_offset_is_refused_as_lookahead():
    """The single most common way a backtest lies to you."""
    ctx = context(indicators={"sma_10": [D("1")] * 20})

    with pytest.raises(ValueError, match="lookahead"):
        ctx.indicator("sma_10", offset=-1)


def test_the_context_exposes_history_only_up_to_the_current_bar():
    candles = make_candles([float(x) for x in range(50)])
    ctx = context(index=10, candles=candles)

    assert len(ctx.candles) == 11
    assert ctx.candles[-1] is candles[10]


def test_indicator_offsets_read_backwards():
    values = [D(str(x)) for x in range(20)]
    ctx = context(index=10, indicators={"sma_5": values})

    assert ctx.indicator("sma_5") == D("10")
    assert ctx.indicator("sma_5", offset=1) == D("9")
    assert ctx.indicator("sma_5", offset=3) == D("7")


def test_reading_before_the_series_starts_returns_none():
    ctx = context(index=2, indicators={"sma_5": [None, None, D("5")]})

    assert ctx.indicator("sma_5", offset=5) is None
    assert ctx.indicator("sma_5", offset=2) is None
    assert ctx.indicator("sma_5") == D("5")


def test_an_unknown_indicator_returns_none_rather_than_raising():
    assert context().indicator("nope") is None
    assert context().has_indicator("nope") is False


def test_position_helpers():
    assert context(position=10).is_long
    assert context(position=-10).is_short
    assert context(position=0).is_flat


# ==========================================================================
# Moving-average crossover
# ==========================================================================


def crossover_context(
    *, fast_prev, fast_now, slow_prev, slow_now, position=0
) -> StrategyContext:
    """A context sitting exactly on a cross."""
    return context(
        index=1,
        position=position,
        candles=make_candles([100.0, 100.0]),
        indicators={
            "sma_10": [D(str(fast_prev)), D(str(fast_now))],
            "sma_30": [D(str(slow_prev)), D(str(slow_now))],
        },
    )


def test_a_golden_cross_from_flat_buys():
    strategy = MovingAverageCrossover(fast=10, slow=30)

    decision = strategy.on_bar(
        crossover_context(fast_prev=99, fast_now=101, slow_prev=100, slow_now=100)
    )

    assert decision.signal is Signal.BUY
    assert "golden cross" in decision.reason


def test_a_death_cross_from_flat_shorts_when_allowed():
    strategy = MovingAverageCrossover(fast=10, slow=30, allow_short=True)

    decision = strategy.on_bar(
        crossover_context(fast_prev=101, fast_now=99, slow_prev=100, slow_now=100)
    )

    assert decision.signal is Signal.SHORT


def test_a_death_cross_sells_when_shorting_is_disabled():
    strategy = MovingAverageCrossover(fast=10, slow=30, allow_short=False)

    decision = strategy.on_bar(
        crossover_context(
            fast_prev=101, fast_now=99, slow_prev=100, slow_now=100, position=50
        )
    )

    assert decision.signal is Signal.SELL


def test_a_death_cross_from_flat_holds_when_shorting_is_disabled():
    strategy = MovingAverageCrossover(fast=10, slow=30, allow_short=False)

    decision = strategy.on_bar(
        crossover_context(fast_prev=101, fast_now=99, slow_prev=100, slow_now=100)
    )

    assert decision.signal is Signal.HOLD


def test_no_signal_without_an_actual_cross():
    """Fast above slow on both bars is a trend, not a cross."""
    strategy = MovingAverageCrossover(fast=10, slow=30)

    decision = strategy.on_bar(
        crossover_context(fast_prev=105, fast_now=110, slow_prev=100, slow_now=100)
    )

    assert decision.signal is Signal.HOLD


def test_a_golden_cross_while_already_long_holds():
    """Otherwise one cross would pyramid on every subsequent bar."""
    strategy = MovingAverageCrossover(fast=10, slow=30)

    decision = strategy.on_bar(
        crossover_context(
            fast_prev=99, fast_now=101, slow_prev=100, slow_now=100, position=100
        )
    )

    assert decision.signal is Signal.HOLD
    assert decision.reason == "already long"


def test_a_death_cross_while_already_short_holds():
    strategy = MovingAverageCrossover(fast=10, slow=30)

    decision = strategy.on_bar(
        crossover_context(
            fast_prev=101, fast_now=99, slow_prev=100, slow_now=100, position=-100
        )
    )

    assert decision.signal is Signal.HOLD


def test_a_golden_cross_while_short_buys_to_reverse():
    """BUY crosses zero: covers the short and opens the long in one order."""
    strategy = MovingAverageCrossover(fast=10, slow=30)

    decision = strategy.on_bar(
        crossover_context(
            fast_prev=99, fast_now=101, slow_prev=100, slow_now=100, position=-100
        )
    )

    assert decision.signal is Signal.BUY


def test_the_strategy_holds_while_indicators_are_warming_up():
    strategy = MovingAverageCrossover(fast=10, slow=30)

    decision = strategy.on_bar(
        context(index=1, indicators={"sma_10": [None, None], "sma_30": [None, None]})
    )

    assert decision.signal is Signal.HOLD
    assert "warming up" in decision.reason


def test_the_strategy_declares_the_indicators_it_needs():
    strategy = MovingAverageCrossover(fast=8, slow=21)

    keys = [spec.key for spec in strategy.required_indicators()]

    assert keys == ["sma_8", "sma_21"]


def test_warmup_covers_the_slow_average_plus_a_previous_bar():
    assert MovingAverageCrossover(fast=10, slow=30).warmup_bars() == 30


def test_fast_must_be_shorter_than_slow():
    with pytest.raises(ValueError, match="shorter than"):
        MovingAverageCrossover(fast=30, slow=10)


# ==========================================================================
# Registry
# ==========================================================================


def test_the_example_strategy_is_registered():
    assert "ma_crossover" in available_strategies()


def test_a_strategy_is_built_with_defaults():
    strategy = create_strategy("ma_crossover")

    assert isinstance(strategy, MovingAverageCrossover)
    assert strategy.fast == 10
    assert strategy.slow == 30


def test_parameters_override_defaults():
    strategy = create_strategy("ma_crossover", {"fast": 5, "slow": 20})

    assert (strategy.fast, strategy.slow) == (5, 20)


def test_an_integer_flag_becomes_a_boolean():
    """JSON has no bool/int distinction worth relying on here."""
    strategy = create_strategy("ma_crossover", {"allow_short": 0})

    assert strategy.allow_short is False


def test_an_unknown_strategy_is_rejected_with_the_available_list():
    with pytest.raises(UnknownStrategyError, match="Available"):
        create_strategy("does_not_exist")


def test_invalid_parameters_are_rejected():
    with pytest.raises(InvalidStrategyParamsError, match="shorter than"):
        create_strategy("ma_crossover", {"fast": 50, "slow": 10})


def test_an_unexpected_parameter_is_rejected():
    with pytest.raises(InvalidStrategyParamsError):
        create_strategy("ma_crossover", {"nonsense": 1})


def test_metadata_lists_every_parameter():
    entry = describe_all()[0]

    assert entry["name"] == "ma_crossover"
    assert {param["name"] for param in entry["params"]} == {
        "fast",
        "slow",
        "allow_short",
    }
