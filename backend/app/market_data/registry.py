"""Provider selection.

The concrete provider is chosen by ``MARKET_DATA_PROVIDER`` at startup, so
swapping feeds is a configuration change rather than a code change. Adding a
provider means writing one module and adding one entry to ``_PROVIDERS``.
"""

from collections.abc import Callable

from app.core.config import settings
from app.core.logging import get_logger
from app.market_data.base import MarketDataProvider
from app.market_data.yahoo import YahooFinanceProvider

logger = get_logger(__name__)


def _build_yahoo() -> MarketDataProvider:
    return YahooFinanceProvider(timeout_seconds=settings.MARKET_DATA_TIMEOUT_SECONDS)


#: Registered providers, keyed by the value of MARKET_DATA_PROVIDER.
_PROVIDERS: dict[str, Callable[[], MarketDataProvider]] = {
    "yahoo": _build_yahoo,
}

_instance: MarketDataProvider | None = None


def available_providers() -> list[str]:
    return sorted(_PROVIDERS)


def create_provider(name: str | None = None) -> MarketDataProvider:
    """Instantiate a provider by name. Prefer ``get_provider`` at runtime."""
    key = (name or settings.MARKET_DATA_PROVIDER).strip().lower()
    factory = _PROVIDERS.get(key)
    if factory is None:
        raise ValueError(
            f"Unknown market-data provider '{key}'. "
            f"Available: {', '.join(available_providers())}."
        )
    return factory()


def get_provider() -> MarketDataProvider:
    """Return the process-wide provider, building it on first use.

    One instance means one pooled HTTP connection set rather than a new client
    per request.
    """
    global _instance
    if _instance is None:
        _instance = create_provider()
        logger.info("Market-data provider: %s", _instance.capabilities.name)
    return _instance


async def close_provider() -> None:
    """Release the provider's resources on application shutdown."""
    global _instance
    if _instance is not None:
        await _instance.aclose()
        _instance = None
