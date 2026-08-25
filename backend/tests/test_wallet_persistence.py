"""Persistence tests.

These prove the wallet lives in PostgreSQL rather than in process memory: each
test reads back through a brand-new engine and connection pool, which is what
an application restart amounts to from the database's point of view.
"""

from decimal import Decimal

import pytest
from httpx import AsyncClient
from sqlalchemy import select, text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.pool import NullPool

from app.core.config import settings
from app.models.wallet import Wallet

WALLET_URL = "/api/v1/wallet"


async def _read_wallet_through_a_fresh_connection() -> Wallet | None:
    """Read the wallet using an engine the application never touched."""
    fresh_engine = create_async_engine(settings.DATABASE_URL, poolclass=NullPool)
    fresh_sessions = async_sessionmaker(bind=fresh_engine, class_=AsyncSession)
    try:
        async with fresh_sessions() as session:
            result = await session.execute(select(Wallet))
            return result.scalar_one_or_none()
    finally:
        await fresh_engine.dispose()


async def test_wallet_survives_a_simulated_restart(client: AsyncClient):
    created = await client.post(f"{WALLET_URL}/initialize")
    assert created.status_code == 201

    wallet = await _read_wallet_through_a_fresh_connection()

    assert wallet is not None, "wallet was not persisted to PostgreSQL"
    assert wallet.cash_balance == settings.WALLET_INITIAL_BALANCE


async def test_balance_changes_survive_a_simulated_restart(
    client: AsyncClient, session: AsyncSession
):
    await client.post(f"{WALLET_URL}/initialize")

    stored = (await session.execute(select(Wallet))).scalar_one()
    stored.cash_balance = Decimal("123456.78")
    await session.commit()

    wallet = await _read_wallet_through_a_fresh_connection()

    assert wallet is not None
    assert wallet.cash_balance == Decimal("123456.78")


async def test_reset_is_durable(client: AsyncClient, session: AsyncSession):
    await client.post(f"{WALLET_URL}/initialize")

    stored = (await session.execute(select(Wallet))).scalar_one()
    stored.cash_balance = Decimal("1.00")
    await session.commit()

    await client.post(f"{WALLET_URL}/reset")

    wallet = await _read_wallet_through_a_fresh_connection()
    assert wallet is not None
    assert wallet.cash_balance == settings.WALLET_INITIAL_BALANCE


async def test_money_keeps_exact_decimal_precision(client: AsyncClient):
    """0.1 + 0.2 must not drift — the column is NUMERIC, not floating point."""
    await client.post(f"{WALLET_URL}/initialize", json={"initial_balance": "10000.10"})

    wallet = await _read_wallet_through_a_fresh_connection()

    assert wallet is not None
    assert wallet.cash_balance == Decimal("10000.10")
    assert isinstance(wallet.cash_balance, Decimal)


# --------------------------------------------------------------------------
# Database-level invariants
# --------------------------------------------------------------------------


async def test_second_wallet_cannot_be_inserted(
    client: AsyncClient, session: AsyncSession
):
    """The singleton CHECK constraint is enforced by PostgreSQL itself."""
    await client.post(f"{WALLET_URL}/initialize")

    with pytest.raises(IntegrityError):
        await session.execute(
            text(
                "INSERT INTO wallet (id, currency, initial_balance, cash_balance) "
                "VALUES (2, 'INR', 100, 100)"
            )
        )
        await session.commit()
    await session.rollback()


async def test_negative_cash_balance_is_rejected(
    client: AsyncClient, session: AsyncSession
):
    await client.post(f"{WALLET_URL}/initialize")

    with pytest.raises(IntegrityError):
        await session.execute(text("UPDATE wallet SET cash_balance = -1 WHERE id = 1"))
        await session.commit()
    await session.rollback()
