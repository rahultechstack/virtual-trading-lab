"""Wallet endpoints — transport only, logic lives in WalletService."""

from fastapi import APIRouter, Response, status

from app.api.deps import DbSession
from app.schemas.wallet import (
    WalletInitializeRequest,
    WalletResetRequest,
    WalletResponse,
)
from app.services.wallet_service import WalletService

router = APIRouter(prefix="/wallet", tags=["wallet"])


@router.get(
    "",
    response_model=WalletResponse,
    summary="Get the virtual wallet",
    responses={404: {"description": "Wallet has not been initialised yet."}},
)
async def get_wallet(session: DbSession) -> WalletResponse:
    """Return the single virtual account with its current cash balance."""
    wallet = await WalletService(session).get_wallet()
    return WalletResponse.model_validate(wallet)


@router.post(
    "/initialize",
    response_model=WalletResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Create the wallet if it does not exist",
)
async def initialize_wallet(
    session: DbSession,
    response: Response,
    payload: WalletInitializeRequest | None = None,
) -> WalletResponse:
    """Idempotent.

    Returns **201** when the wallet is created and **200** when it already
    existed — an accidental repeat call never overwrites a balance.
    """
    requested = payload.initial_balance if payload else None
    wallet, created = await WalletService(session).initialize_wallet(requested)

    if not created:
        response.status_code = status.HTTP_200_OK

    return WalletResponse.model_validate(wallet)


@router.post(
    "/reset",
    response_model=WalletResponse,
    summary="Reset cash back to the opening capital",
    responses={404: {"description": "Wallet has not been initialised yet."}},
)
async def reset_wallet(
    session: DbSession,
    payload: WalletResetRequest | None = None,
) -> WalletResponse:
    """Restore ``cash_balance`` to ``initial_balance``.

    Supply ``initial_balance`` to re-open the account at a different amount.
    """
    requested = payload.initial_balance if payload else None
    wallet = await WalletService(session).reset_wallet(requested)
    return WalletResponse.model_validate(wallet)
