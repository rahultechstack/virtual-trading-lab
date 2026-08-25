"""Strategy registry.

Strategies are looked up by name and constructed with validated parameters,
so a strategy can be selected from configuration or an API request without
the caller importing it.
"""

from collections.abc import Callable
from decimal import Decimal

from app.core.exceptions import DomainError
from app.strategies.base import Strategy
from app.strategies.ma_crossover import MovingAverageCrossover


class UnknownStrategyError(DomainError):
    status_code = 400
    code = "unknown_strategy"


class InvalidStrategyParamsError(DomainError):
    status_code = 400
    code = "invalid_strategy_params"


#: Registered strategies. Adding one means a module and an entry here.
_STRATEGIES: dict[str, Callable[..., Strategy]] = {
    MovingAverageCrossover.name: MovingAverageCrossover,
}


def available_strategies() -> list[str]:
    return sorted(_STRATEGIES)


def describe_all() -> list[dict]:
    """Metadata for every strategy, for an API or a UI to render."""
    return [_build(name).describe() for name in available_strategies()]


def _build(name: str, params: dict | None = None) -> Strategy:
    factory = _STRATEGIES[name]
    return factory(**(params or {}))


def create_strategy(name: str, params: dict | None = None) -> Strategy:
    """Instantiate a strategy by name.

    Parameters are validated by the strategy's own constructor, so a rule that
    spans two of them -- fast shorter than slow, say -- is enforced in one
    place rather than duplicated here.
    """
    key = name.strip().lower()
    if key not in _STRATEGIES:
        raise UnknownStrategyError(
            f"Unknown strategy '{name}'. Available: {', '.join(available_strategies())}."
        )

    cleaned = _coerce(params or {})
    try:
        return _build(key, cleaned)
    except TypeError as exc:
        raise InvalidStrategyParamsError(
            f"{key}: unexpected parameter. {exc}"
        ) from exc
    except ValueError as exc:
        raise InvalidStrategyParamsError(f"{key}: {exc}") from exc


def _coerce(params: dict) -> dict:
    """Turn JSON values into what the constructors expect.

    JSON has no integer/boolean distinction worth relying on here, so numbers
    that are whole become ints and 0/1 flags become bools where the name says
    so.
    """
    cleaned: dict = {}
    for key, value in params.items():
        if isinstance(value, bool):
            cleaned[key] = value
        elif key.startswith("allow_") or key.startswith("use_"):
            cleaned[key] = bool(value)
        elif isinstance(value, (int, float, Decimal)) and float(value).is_integer():
            cleaned[key] = int(value)
        else:
            cleaned[key] = value
    return cleaned
