"""Market-data abstraction.

    MarketDataProvider          (contract)
        |
        +-- YahooFinanceProvider    (integration)
        |
    RelianceMarketDataService   (platform rules)

Import the abstraction, never a concrete provider.
"""

from app.market_data.base import MarketDataProvider
from app.market_data.registry import (
    available_providers,
    close_provider,
    create_provider,
    get_provider,
)

__all__ = [
    "MarketDataProvider",
    "available_providers",
    "close_provider",
    "create_provider",
    "get_provider",
]
