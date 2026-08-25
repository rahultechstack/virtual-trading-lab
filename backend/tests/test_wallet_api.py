"""API-level tests for wallet creation, retrieval and reset."""

from decimal import Decimal

import pytest
from httpx import AsyncClient

from app.core.config import settings

WALLET_URL = "/api/v1/wallet"
DEFAULT_BALANCE = Decimal("1000000.00")


# --------------------------------------------------------------------------
# Creation
# --------------------------------------------------------------------------


async def test_initialize_creates_wallet_with_configured_balance(client: AsyncClient):
    response = await client.post(f"{WALLET_URL}/initialize")

    assert response.status_code == 201
    body = response.json()
    assert body["id"] == 1
    assert Decimal(str(body["initial_balance"])) == settings.WALLET_INITIAL_BALANCE
    assert Decimal(str(body["cash_balance"])) == settings.WALLET_INITIAL_BALANCE
    assert body["currency"] == settings.WALLET_CURRENCY


async def test_default_balance_is_ten_lakh(client: AsyncClient):
    """The documented opening capital: INR 10,00,000."""
    response = await client.post(f"{WALLET_URL}/initialize")

    assert Decimal(str(response.json()["cash_balance"])) == DEFAULT_BALANCE


async def test_initialize_accepts_custom_balance(client: AsyncClient):
    response = await client.post(
        f"{WALLET_URL}/initialize", json={"initial_balance": "250000.50"}
    )

    assert response.status_code == 201
    body = response.json()
    assert Decimal(str(body["initial_balance"])) == Decimal("250000.50")
    assert Decimal(str(body["cash_balance"])) == Decimal("250000.50")


async def test_initialize_is_idempotent_and_never_overwrites(client: AsyncClient):
    """A second call must return the existing wallet, not reset it."""
    await client.post(f"{WALLET_URL}/initialize", json={"initial_balance": "5000.00"})

    second = await client.post(
        f"{WALLET_URL}/initialize", json={"initial_balance": "9999.00"}
    )

    assert second.status_code == 200, "existing wallet should return 200, not 201"
    assert Decimal(str(second.json()["initial_balance"])) == Decimal("5000.00")


async def test_initialize_rejects_non_positive_balance(client: AsyncClient):
    response = await client.post(
        f"{WALLET_URL}/initialize", json={"initial_balance": "0"}
    )

    assert response.status_code == 422


# --------------------------------------------------------------------------
# Retrieval
# --------------------------------------------------------------------------


async def test_get_wallet_returns_404_before_initialization(client: AsyncClient):
    response = await client.get(WALLET_URL)

    assert response.status_code == 404
    assert response.json()["error"]["code"] == "wallet_not_found"


async def test_get_wallet_returns_the_wallet(client: AsyncClient):
    await client.post(f"{WALLET_URL}/initialize")

    response = await client.get(WALLET_URL)

    assert response.status_code == 200
    body = response.json()
    assert body["id"] == 1
    assert Decimal(str(body["cash_balance"])) == DEFAULT_BALANCE
    assert body["created_at"] and body["updated_at"]


# --------------------------------------------------------------------------
# Reset
# --------------------------------------------------------------------------


async def test_reset_restores_cash_to_initial_balance(
    client: AsyncClient, spend_cash
):
    await client.post(f"{WALLET_URL}/initialize")
    await spend_cash(Decimal("400000.00"))

    assert Decimal(str((await client.get(WALLET_URL)).json()["cash_balance"])) == Decimal(
        "600000.00"
    )

    response = await client.post(f"{WALLET_URL}/reset")

    assert response.status_code == 200
    assert Decimal(str(response.json()["cash_balance"])) == DEFAULT_BALANCE


async def test_reset_can_reopen_at_a_new_balance(client: AsyncClient):
    await client.post(f"{WALLET_URL}/initialize")

    response = await client.post(
        f"{WALLET_URL}/reset", json={"initial_balance": "300000.00"}
    )

    body = response.json()
    assert Decimal(str(body["initial_balance"])) == Decimal("300000.00")
    assert Decimal(str(body["cash_balance"])) == Decimal("300000.00")


async def test_reset_returns_404_before_initialization(client: AsyncClient):
    response = await client.post(f"{WALLET_URL}/reset")

    assert response.status_code == 404
    assert response.json()["error"]["code"] == "wallet_not_found"


@pytest.fixture
def spend_cash(session):
    """Simulate cash leaving the wallet without any trading engine."""

    async def _spend(amount: Decimal) -> None:
        from app.repositories.wallet_repository import WalletRepository

        repo = WalletRepository(session)
        wallet = await repo.get_for_update()
        assert wallet is not None
        wallet.cash_balance = wallet.cash_balance - amount
        await session.commit()

    return _spend
