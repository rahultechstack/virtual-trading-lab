"""Provider construction and the equity singleton.

Every provider implementation is registered in ``_PROVIDERS`` here, so adding a
feed means writing one module and adding one entry -- swapping feeds stays a
configuration change rather than a code change.

``get_provider()`` returns the **equity** provider, which is what the majority
of the codebase historically meant by "the provider". Selection *by asset
class* lives in ``app.market_data.router``; that is what callers holding an
instrument should use, so a crypto symbol is never priced off the equity feed.
"""

from collections.abc import Callable

from app.core.config import settings
from app.core.logging import get_logger
from app.market_data.base import MarketDataProvider
from app.market_data.crypto import YahooCryptoProvider
from app.market_data.mock import MockMarketDataProvider
from app.market_data.yahoo import YahooFinanceProvider

logger = get_logger(__name__)


def _build_yahoo() -> MarketDataProvider:
    return YahooFinanceProvider(timeout_seconds=settings.MARKET_DATA_TIMEOUT_SECONDS)


def _build_yahoo_crypto() -> MarketDataProvider:
    return YahooCryptoProvider.from_settings()


def _build_mock() -> MarketDataProvider:
    return MockMarketDataProvider.from_settings()


#: Registered providers, keyed by the value of MARKET_DATA_PROVIDER or
#: CRYPTO_MARKET_DATA_PROVIDER. A name is just a name -- nothing stops a
#: provider serving both asset classes if it genuinely can.
_PROVIDERS: dict[str, Callable[[], MarketDataProvider]] = {
    "yahoo": _build_yahoo,
    "yahoo_crypto": _build_yahoo_crypto,
    "mock": _build_mock,
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
    """Return the process-wide **equity** provider, building it on first use.

    One instance means one pooled HTTP connection set rather than a new client
    per request. For an instrument whose asset class may not be STOCK, use
    ``app.market_data.router.provider_for()`` instead.
    """
    global _instance
    if _instance is None:
        _instance = create_provider()
        capabilities = _instance.capabilities
        logger.info("Market-data provider: %s", capabilities.name)
        if capabilities.is_mock:
            logger.warning(
                "MOCK MARKET DATA IS ACTIVE. Prices are simulated and have no "
                "relationship to the real market. Set MARKET_DATA_PROVIDER to a "
                "real provider before relying on anything this returns."
            )
    return _instance


def is_default_provider(provider: MarketDataProvider) -> bool:
    """Whether ``provider`` is the process-wide equity singleton.

    Used by the API layer to tell "nobody chose a provider" apart from "a
    caller (a test) explicitly supplied one". The first case must route by
    asset class; the second must honour what was supplied.
    """
    return _instance is not None and provider is _instance


async def close_provider() -> None:
    """Release every provider's resources on application shutdown."""
    global _instance
    # Per-asset-class providers (crypto today) are owned by the router.
    from app.market_data.router import close_providers

    await close_providers()

    if _instance is not None:
        await _instance.aclose()
        _instance = None
