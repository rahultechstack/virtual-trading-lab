"""Persistence operations for the single wallet row."""

from decimal import Decimal

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.wallet import WALLET_ID, Wallet


class WalletRepository:
    """All wallet SQL lives here."""

    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def get(self) -> Wallet | None:
        """Return the wallet, or ``None`` if it has never been initialised."""
        result = await self._session.execute(
            select(Wallet).where(Wallet.id == WALLET_ID)
        )
        return result.scalar_one_or_none()

    async def get_for_update(self) -> Wallet | None:
        """Row-locked read.

        Later stages settle orders against the balance concurrently; taking the
        lock here keeps read-modify-write sequences serialised.
        """
        result = await self._session.execute(
            select(Wallet).where(Wallet.id == WALLET_ID).with_for_update()
        )
        return result.scalar_one_or_none()

    async def create(self, initial_balance: Decimal, currency: str) -> Wallet:
        """Insert the wallet with cash equal to its opening capital."""
        wallet = Wallet(
            id=WALLET_ID,
            currency=currency,
            initial_balance=initial_balance,
            cash_balance=initial_balance,
        )
        self._session.add(wallet)
        await self._session.flush()
        return wallet
