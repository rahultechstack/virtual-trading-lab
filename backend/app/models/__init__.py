"""SQLAlchemy models.

Every model must be imported here so that ``Base.metadata`` is fully populated
before Alembic autogenerate inspects it.
"""

from app.db.base import Base
from app.models.automatic_order import (
    AutomaticOrder,
    AutomaticOrderStatus,
    AutomaticOrderType,
    TriggerCondition,
)
from app.models.enums import OrderSide, OrderStatus, OrderType
from app.models.portfolio_snapshot import PortfolioSnapshot, SnapshotSource
from app.models.trading import Order, Position, Trade
from app.models.wallet import WALLET_ID, Wallet

__all__ = [
    "AutomaticOrder",
    "AutomaticOrderStatus",
    "AutomaticOrderType",
    "Base",
    "Order",
    "OrderSide",
    "OrderStatus",
    "OrderType",
    "PortfolioSnapshot",
    "Position",
    "SnapshotSource",
    "Trade",
    "TriggerCondition",
    "WALLET_ID",
    "Wallet",
]
