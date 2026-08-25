"""Indicator catalogue and request parsing.

An indicator is requested as a colon-separated spec: ``sma:20``,
``macd:12:26:9``, ``bbands:20:2``, ``vwap``. Omitted parameters fall back to
the conventional defaults recorded here.
"""

from dataclasses import dataclass
from decimal import Decimal
from enum import StrEnum

from app.core.exceptions import DomainError


class InvalidIndicatorError(DomainError):
    """The requested indicator or its parameters are not valid."""

    status_code = 400
    code = "invalid_indicator"


class IndicatorType(StrEnum):
    SMA = "sma"
    EMA = "ema"
    RSI = "rsi"
    MACD = "macd"
    BBANDS = "bbands"
    VWAP = "vwap"


class Pane(StrEnum):
    """Where the indicator belongs on screen.

    Overlays share the price axis; oscillators have their own scale and must
    be drawn in a separate pane beneath it.
    """

    PRICE = "price"
    SEPARATE = "separate"


class SeriesStyle(StrEnum):
    LINE = "line"
    HISTOGRAM = "histogram"


@dataclass(frozen=True)
class ParamDef:
    """One tunable parameter of an indicator."""

    name: str
    default: int | Decimal
    minimum: int | Decimal
    maximum: int | Decimal
    is_decimal: bool = False


@dataclass(frozen=True)
class IndicatorDef:
    """Everything static about an indicator."""

    type: IndicatorType
    display_name: str
    pane: Pane
    params: tuple[ParamDef, ...]
    description: str
    #: Fixed bounds for the oscillator's own axis, where it has them.
    scale_min: Decimal | None = None
    scale_max: Decimal | None = None


CATALOGUE: dict[IndicatorType, IndicatorDef] = {
    IndicatorType.SMA: IndicatorDef(
        type=IndicatorType.SMA,
        display_name="SMA",
        pane=Pane.PRICE,
        params=(ParamDef("period", 20, 2, 500),),
        description="Simple moving average of the close.",
    ),
    IndicatorType.EMA: IndicatorDef(
        type=IndicatorType.EMA,
        display_name="EMA",
        pane=Pane.PRICE,
        params=(ParamDef("period", 21, 2, 500),),
        description="Exponential moving average; weights recent closes more heavily.",
    ),
    IndicatorType.RSI: IndicatorDef(
        type=IndicatorType.RSI,
        display_name="RSI",
        pane=Pane.SEPARATE,
        params=(ParamDef("period", 14, 2, 200),),
        description="Relative Strength Index, bounded 0-100.",
        scale_min=Decimal("0"),
        scale_max=Decimal("100"),
    ),
    IndicatorType.MACD: IndicatorDef(
        type=IndicatorType.MACD,
        display_name="MACD",
        pane=Pane.SEPARATE,
        params=(
            ParamDef("fast", 12, 2, 200),
            ParamDef("slow", 26, 3, 400),
            ParamDef("signal", 9, 2, 200),
        ),
        description="Moving Average Convergence Divergence, with signal and histogram.",
    ),
    IndicatorType.BBANDS: IndicatorDef(
        type=IndicatorType.BBANDS,
        display_name="Bollinger",
        pane=Pane.PRICE,
        params=(
            ParamDef("period", 20, 2, 500),
            ParamDef(
                "stddev", Decimal("2"), Decimal("0.1"), Decimal("10"), is_decimal=True
            ),
        ),
        description="Bollinger Bands: a moving average with standard-deviation envelopes.",
    ),
    IndicatorType.VWAP: IndicatorDef(
        type=IndicatorType.VWAP,
        display_name="VWAP",
        pane=Pane.PRICE,
        params=(ParamDef("period", 20, 2, 500),),
        description=(
            "Volume Weighted Average Price. Anchored to the trading session on "
            "intraday intervals; a rolling window of 'period' bars on daily and "
            "above, where a per-bar session anchor would be meaningless."
        ),
    ),
}

#: Cap on how many indicators one request may ask for.
MAX_INDICATORS = 10


@dataclass(frozen=True)
class IndicatorSpec:
    """A requested indicator with its resolved parameters."""

    type: IndicatorType
    params: tuple[int | Decimal, ...]

    @property
    def definition(self) -> IndicatorDef:
        return CATALOGUE[self.type]

    @property
    def key(self) -> str:
        """Stable identifier, e.g. ``sma_20`` or ``macd_12_26_9``."""
        parts = [self.type.value, *(_format_param(p) for p in self.params)]
        return "_".join(parts)

    @property
    def label(self) -> str:
        """Human label, e.g. ``SMA(20)``."""
        rendered = ", ".join(_format_param(p) for p in self.params)
        return f"{self.definition.display_name}({rendered})"

    def param(self, name: str) -> int | Decimal:
        for index, definition in enumerate(self.definition.params):
            if definition.name == name:
                return self.params[index]
        raise KeyError(name)  # pragma: no cover - defensive

    def as_dict(self) -> dict[str, int | float]:
        return {
            definition.name: (
                float(value) if isinstance(value, Decimal) else value
            )
            for definition, value in zip(self.definition.params, self.params)
        }


def _format_param(value: int | Decimal) -> str:
    if isinstance(value, Decimal):
        return format(value.normalize(), "f")
    return str(value)


def parse_spec(raw: str) -> IndicatorSpec:
    """Parse one ``name:p1:p2`` spec, applying defaults and validating bounds."""
    parts = [part.strip() for part in raw.strip().split(":") if part.strip() != ""]
    if not parts:
        raise InvalidIndicatorError("Empty indicator specification.")

    name = parts[0].lower()
    try:
        indicator_type = IndicatorType(name)
    except ValueError:
        available = ", ".join(t.value for t in IndicatorType)
        raise InvalidIndicatorError(
            f"Unknown indicator '{name}'. Available: {available}."
        ) from None

    definition = CATALOGUE[indicator_type]
    supplied = parts[1:]

    if len(supplied) > len(definition.params):
        raise InvalidIndicatorError(
            f"{name} takes at most {len(definition.params)} parameter(s), "
            f"got {len(supplied)}."
        )

    values: list[int | Decimal] = []
    for index, param in enumerate(definition.params):
        if index < len(supplied):
            values.append(_coerce(name, param, supplied[index]))
        else:
            values.append(param.default)

    _validate_relationships(indicator_type, values)
    return IndicatorSpec(type=indicator_type, params=tuple(values))


def _coerce(name: str, param: ParamDef, raw: str) -> int | Decimal:
    try:
        value: int | Decimal = Decimal(raw) if param.is_decimal else int(raw)
    except (ValueError, ArithmeticError):
        expected = "a number" if param.is_decimal else "a whole number"
        raise InvalidIndicatorError(
            f"{name}: {param.name} must be {expected}, got '{raw}'."
        ) from None

    if value < param.minimum or value > param.maximum:
        raise InvalidIndicatorError(
            f"{name}: {param.name} must be between {param.minimum} and "
            f"{param.maximum}, got {value}."
        )
    return value


def _validate_relationships(
    indicator_type: IndicatorType, values: list[int | Decimal]
) -> None:
    """Checks that span more than one parameter."""
    if indicator_type is IndicatorType.MACD:
        fast, slow, _signal = values
        if fast >= slow:
            raise InvalidIndicatorError(
                f"macd: fast ({fast}) must be shorter than slow ({slow})."
            )


def parse_specs(raw: str | None) -> list[IndicatorSpec]:
    """Parse a comma-separated list of specs, rejecting duplicates."""
    if raw is None or not raw.strip():
        return []

    specs: list[IndicatorSpec] = []
    seen: set[str] = set()

    for entry in raw.split(","):
        if not entry.strip():
            continue
        spec = parse_spec(entry)
        if spec.key in seen:
            continue  # Asking twice is harmless; compute once.
        seen.add(spec.key)
        specs.append(spec)

    if len(specs) > MAX_INDICATORS:
        raise InvalidIndicatorError(
            f"At most {MAX_INDICATORS} indicators per request, got {len(specs)}."
        )
    return specs
