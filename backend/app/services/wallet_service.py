"""Wallet business logic.

Owns the transaction boundary for wallet mutations and raises domain errors;
it never touches HTTP.
"""

from decimal import Decimal

from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.core.exceptions import WalletNotFoundError
from app.core.logging import get_logger
from app.models.wallet import Wallet
from app.repositories.wallet_repository import WalletRepository

logger = get_logger(__name__)


class WalletService:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session
        self._repo = WalletRepository(session)

    async def get_wallet(self) -> Wallet:
        """Return the wallet or fail if it has not been initialised."""
        wallet = await self._repo.get()
        if wallet is None:
            raise WalletNotFoundError()
        return wallet

    async def initialize_wallet(
        self, initial_balance: Decimal | None = None
    ) -> tuple[Wallet, bool]:
        """Create the wallet if absent.

        Idempotent: calling it on an already-initialised wallet returns the
        existing row untouched, so an accidental second call can never wipe a
        balance. Returns ``(wallet, created)``.
        """
        existing = await self._repo.get()
        if existing is not None:
            return existing, False

        amount = initial_balance if initial_balance is not None else settings.WALLET_INITIAL_BALANCE

        try:
            wallet = await self._repo.create(
                initial_balance=amount, currency=settings.WALLET_CURRENCY
            )
            await self._session.commit()
        except IntegrityError:
            # A concurrent request won the race and inserted id=1 first.
            # The singleton constraint did its job; adopt the winner's row.
            await self._session.rollback()
            logger.info("Concurrent wallet initialisation detected; reusing existing row.")
            wallet = await self.get_wallet()
            return wallet, False

        await self._session.refresh(wallet)
        logger.info("Wallet initialised with %s %s", amount, settings.WALLET_CURRENCY)
        return wallet, True

    async def reset_wallet(self, initial_balance: Decimal | None = None) -> Wallet:
        """Restore cash to the opening capital.

        Supplying ``initial_balance`` re-opens the account at a new amount;
        omitting it restores the existing one.
        """
        wallet = await self._repo.get_for_update()
        if wallet is None:
            raise WalletNotFoundError()

        if initial_balance is not None:
            wallet.initial_balance = initial_balance

        wallet.cash_balance = wallet.initial_balance

        await self._session.commit()
        await self._session.refresh(wallet)
        logger.info("Wallet reset to %s %s", wallet.cash_balance, wallet.currency)
        return wallet
