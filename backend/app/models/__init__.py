"""SQLAlchemy models.

Every model must be imported here so that ``Base.metadata`` is fully populated
before Alembic autogenerate inspects it.
"""

from app.db.base import Base
from app.models.wallet import WALLET_ID, Wallet

__all__ = ["Base", "Wallet", "WALLET_ID"]
