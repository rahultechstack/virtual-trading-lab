"""Moving-average crossover.

The example strategy, deliberately the simplest thing that exercises the whole
framework: long entries, exits, and optional short selling.

    fast SMA crosses **above** slow  ->  bullish
    fast SMA crosses **below** slow  ->  bearish

A *cross* means the relationship changed between the previous bar and this
one. Comparing only the current bar would re-fire the same signal on every
subsequent bar, which is a classic way to turn one trade into fifty.
"""

from decimal import Decimal

from app.indicators.definitions import IndicatorSpec, IndicatorType
from app.strategies.base import (
    Decision,
    Signal,
    Strategy,
    StrategyContext,
    StrategyParam,
)


class MovingAverageCrossover(Strategy):
    """Goes long on a golden cross, flat or short on a death cross."""

    name = "ma_crossover"
    display_name = "Moving Average Crossover"
    description = (
        "Buys when the fast SMA crosses above the slow SMA and sells when it "
        "crosses back below. With shorting enabled a death cross opens a "
        "short instead of merely closing the long."
    )
    params = (
        StrategyParam("fast", 10, 2, 200, "Fast SMA period."),
        StrategyParam("slow", 30, 3, 500, "Slow SMA period."),
        StrategyParam(
            "allow_short", 1, 0, 1, "1 to short on a death cross, 0 to only go flat."
        ),
    )

    def __init__(
        self, *, fast: int = 10, slow: int = 30, allow_short: bool = True
    ) -> None:
        if fast >= slow:
            raise ValueError(
                f"fast ({fast}) must be shorter than slow ({slow})."
            )
        self.fast = fast
        self.slow = slow
        self.allow_short = allow_short

        self._fast_spec = IndicatorSpec(IndicatorType.SMA, (fast,))
        self._slow_spec = IndicatorSpec(IndicatorType.SMA, (slow,))

    # -- framework hooks -------------------------------------------------

    def required_indicators(self) -> list[IndicatorSpec]:
        return [self._fast_spec, self._slow_spec]

    def warmup_bars(self) -> int:
        """Both averages plus one, so a *previous* bar exists to compare to."""
        return self.slow

    # -- the rule --------------------------------------------------------

    def on_bar(self, context: StrategyContext) -> Decision:
        fast_now = context.indicator(self._fast_spec.key)
        slow_now = context.indicator(self._slow_spec.key)
        fast_prev = context.indicator(self._fast_spec.key, offset=1)
        slow_prev = context.indicator(self._slow_spec.key, offset=1)

        if None in (fast_now, slow_now, fast_prev, slow_prev):
            return Decision.hold("indicators still warming up")

        crossed_up = fast_prev <= slow_prev and fast_now > slow_now
        crossed_down = fast_prev >= slow_prev and fast_now < slow_now

        if crossed_up:
            return self._on_bullish_cross(context, fast_now, slow_now)
        if crossed_down:
            return self._on_bearish_cross(context, fast_now, slow_now)

        return Decision.hold()

    def _on_bullish_cross(
        self, context: StrategyContext, fast: Decimal, slow: Decimal
    ) -> Decision:
        reason = f"golden cross: SMA{self.fast} {fast} > SMA{self.slow} {slow}"

        if context.is_long:
            return Decision.hold("already long")
        # A BUY from a short position covers it and opens the long in one
        # order -- the same crossing behaviour the live engine implements.
        return Decision(signal=Signal.BUY, reason=reason)

    def _on_bearish_cross(
        self, context: StrategyContext, fast: Decimal, slow: Decimal
    ) -> Decision:
        reason = f"death cross: SMA{self.fast} {fast} < SMA{self.slow} {slow}"

        if context.is_short:
            return Decision.hold("already short")

        if self.allow_short:
            # SHORT closes any long and opens the short in one order.
            return Decision(signal=Signal.SHORT, reason=reason)

        if context.is_long:
            return Decision(signal=Signal.SELL, reason=reason)
        return Decision.hold("flat and shorting disabled")
