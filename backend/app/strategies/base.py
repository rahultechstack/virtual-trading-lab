"""Strategy contract.

A strategy sees market data and answers with one of five signals. It has no
knowledge of the wallet, the database, the web layer or the backtester -- it
receives a read-only view of history up to the current bar and returns a
decision.

**No lookahead.** ``StrategyContext`` exposes the current bar and everything
before it, and nothing after. Indicator values are read by offset backwards
from the current bar, so a strategy cannot accidentally peek at the future --
the single most common way a backtest lies to you.
"""

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from decimal import Decimal
from enum import StrEnum

from app.indicators.definitions import IndicatorSpec
from app.models.enums import OrderSide
from app.schemas.market_data import Candle


class Signal(StrEnum):
    """What a strategy wants to do on this bar."""

    BUY = "BUY"
    SELL = "SELL"
    SHORT = "SHORT"
    COVER = "COVER"
    HOLD = "HOLD"

    @property
    def order_side(self) -> OrderSide | None:
        """The order side this signal maps to, or None for HOLD."""
        return _SIGNAL_TO_SIDE.get(self)

    @property
    def is_actionable(self) -> bool:
        return self is not Signal.HOLD


_SIGNAL_TO_SIDE: dict[Signal, OrderSide] = {
    Signal.BUY: OrderSide.BUY,
    Signal.SELL: OrderSide.SELL,
    Signal.SHORT: OrderSide.SHORT_SELL,
    Signal.COVER: OrderSide.BUY_TO_COVER,
}


@dataclass(frozen=True)
class Decision:
    """A strategy's answer for one bar."""

    signal: Signal
    #: Explicit size. When None the engine's position sizer decides.
    quantity: Decimal | None = None
    #: Why, for the trade log. Purely informational.
    reason: str = ""

    @classmethod
    def hold(cls, reason: str = "") -> "Decision":
        return cls(signal=Signal.HOLD, reason=reason)


@dataclass(frozen=True)
class StrategyContext:
    """What a strategy is allowed to see on this bar.

    ``index`` is the position of the current bar in the full series, and
    ``candles`` is the history *including* it. Nothing beyond it is reachable.
    """

    index: int
    candle: Candle
    candles: list[Candle]
    #: Signed position: > 0 long, 0 flat, < 0 short.
    position: int
    average_price: Decimal
    cash: Decimal
    equity: Decimal
    #: Indicator values keyed by series key, aligned to the full candle series.
    _indicators: dict[str, list[Decimal | None]] = field(default_factory=dict)

    @property
    def close(self) -> Decimal:
        return self.candle.close

    @property
    def is_long(self) -> bool:
        return self.position > 0

    @property
    def is_short(self) -> bool:
        return self.position < 0

    @property
    def is_flat(self) -> bool:
        return self.position == 0

    def indicator(self, key: str, offset: int = 0) -> Decimal | None:
        """Indicator value ``offset`` bars back from the current one.

        ``offset=0`` is this bar, ``offset=1`` the previous. Returns ``None``
        before the indicator has warmed up. A negative offset would be a peek
        into the future and is refused.
        """
        if offset < 0:
            raise ValueError(
                "Negative offsets would read future bars, which is lookahead bias."
            )
        target = self.index - offset
        if target < 0:
            return None
        series = self._indicators.get(key)
        if series is None or target >= len(series):
            return None
        return series[target]

    def has_indicator(self, key: str, offset: int = 0) -> bool:
        return self.indicator(key, offset) is not None


@dataclass(frozen=True)
class StrategyParam:
    """A tunable parameter, for validation and for a UI to render."""

    name: str
    default: int | Decimal
    minimum: int | Decimal
    maximum: int | Decimal
    description: str = ""


class Strategy(ABC):
    """Base class for every strategy.

    Implementations declare the indicators they need, and the engine
    precomputes them once over the whole series before the run. That keeps
    strategies free of calculation code and makes them cheap per bar.
    """

    #: Stable identifier used by the API.
    name: str = "unnamed"
    display_name: str = "Unnamed strategy"
    description: str = ""
    params: tuple[StrategyParam, ...] = ()

    @abstractmethod
    def required_indicators(self) -> list[IndicatorSpec]:
        """Indicators this strategy reads, precomputed before the run."""

    @abstractmethod
    def on_bar(self, context: StrategyContext) -> Decision:
        """Decide what to do on this bar."""

    def warmup_bars(self) -> int:
        """Bars to skip before the strategy is asked anything.

        Defaults to zero; a strategy that needs an indicator to have warmed up
        should report that here so the engine does not call it with nothing to
        work from.
        """
        return 0

    def reset(self) -> None:
        """Clear any per-run state. Called once before each backtest."""

    def describe(self) -> dict:
        """Metadata for the API."""
        return {
            "name": self.name,
            "display_name": self.display_name,
            "description": self.description,
            "params": [
                {
                    "name": param.name,
                    "default": _plain(param.default),
                    "minimum": _plain(param.minimum),
                    "maximum": _plain(param.maximum),
                    "description": param.description,
                }
                for param in self.params
            ],
        }


def _plain(value: int | Decimal) -> int | float:
    return float(value) if isinstance(value, Decimal) else value
