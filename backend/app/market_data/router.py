"""Provider selection by asset class.

    Instrument -> AssetClass -> MarketDataProvider

    AssetClass.STOCK  -> MARKET_DATA_PROVIDER         (default: yahoo)
    AssetClass.CRYPTO -> CRYPTO_MARKET_DATA_PROVIDER  (default: yahoo_crypto)

The equity feed is never asked for a crypto price and vice versa, because
nothing above this module chooses a provider at all -- callers pass an
instrument and receive whichever feed is configured for its class.

One instance is held per asset class, so each keeps a single pooled HTTP client
rather than building one per request. The equity instance is the *same* object
``app.market_data.registry.get_provider()`` returns, so existing code paths and
any test that swaps that singleton keep working unchanged.
"""

from app.core.logging import get_logger
from app.market_data.base import MarketDataProvider
from app.market_data.instruments import AssetClass, Instrument, resolve_instrument

logger = get_logger(__name__)

#: Asset class -> provider instances, built lazily.
_instances: dict[AssetClass, MarketDataProvider] = {}


def provider_for_asset_class(asset_class: AssetClass) -> MarketDataProvider:
    """The feed configured for an asset class, built on first use."""
    from app.core.config import settings
    from app.market_data.registry import create_provider, get_provider

    if asset_class is AssetClass.STOCK:
        # Deliberately delegates to the existing singleton rather than keeping
        # a second copy: equity behaviour, and anything that monkeypatches it,
        # must not change just because crypto was added.
        return get_provider()

    instance = _instances.get(asset_class)
    if instance is None:
        if asset_class is AssetClass.CRYPTO:
            name = settings.CRYPTO_MARKET_DATA_PROVIDER
        else:  # pragma: no cover - unreachable while the enum is closed
            raise ValueError(f"No market-data provider registered for {asset_class}.")

        instance = create_provider(name)
        _instances[asset_class] = instance
        logger.info(
            "Market-data provider for %s: %s", asset_class, instance.capabilities.name
        )
    return instance


def provider_for(instrument: Instrument) -> MarketDataProvider:
    """The feed that serves one instrument."""
    return provider_for_asset_class(instrument.asset_class)


def provider_for_symbol(symbol: str | None) -> MarketDataProvider:
    """The feed for a symbol. Rejects symbols outside the universe."""
    return provider_for(resolve_instrument(symbol))


async def close_providers() -> None:
    """Release every per-asset-class provider. Called on application shutdown.

    The equity provider is owned by ``app.market_data.registry`` and is closed
    by ``close_provider()`` there, so it is deliberately not touched here.

    Best-effort by design: a provider whose HTTP client was created in a
    different event loop cannot be closed from this one, which happens under
    pytest and on an abrupt reload. Dropping the reference still frees it, and
    failing to release one client must not abort shutdown for the rest.
    """
    for asset_class, instance in list(_instances.items()):
        try:
            await instance.aclose()
        except Exception as exc:  # noqa: BLE001 - shutdown must not fail
            logger.debug("Could not close the %s provider: %s", asset_class, exc)
        finally:
            _instances.pop(asset_class, None)


def reset_providers() -> None:
    """Drop cached instances without closing them. Used by tests."""
    _instances.clear()
