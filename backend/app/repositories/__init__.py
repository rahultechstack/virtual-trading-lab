"""Data-access layer.

Repositories own all SQL. Services orchestrate them and hold business rules;
neither layer knows anything about HTTP.
"""

from app.repositories.wallet_repository import WalletRepository

__all__ = ["WalletRepository"]
