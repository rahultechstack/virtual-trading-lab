"""SQLAlchemy models.

Intentionally empty in Stage 1. Domain models (Wallet, Order, Position, Trade,
Instrument) arrive with the trading-logic stage and must be imported here so
Alembic autogenerate can see them.
"""

from app.db.base import Base

__all__ = ["Base"]
