"""Test fixtures.

Tests run against a real PostgreSQL database — never SQLite — because the
wallet relies on Postgres-specific behaviour (NUMERIC precision, CHECK
constraints, SELECT ... FOR UPDATE). A dedicated database is created, migrated
with Alembic and dropped around the session, so development data is untouched.
"""

import asyncio
import os

# Point the application at the test database BEFORE any app module is imported,
# since app.core.config builds its settings singleton at import time.
_TEST_DB = os.environ.get("TEST_POSTGRES_DB", "virtual_trading_test")
_ADMIN_DB = os.environ.get("POSTGRES_DB", "virtual_trading")
os.environ["POSTGRES_DB"] = _TEST_DB

# Each test may run in its own event loop; a pooled asyncpg connection opened in
# an earlier loop cannot be reused from a later one. NullPool sidesteps this by
# opening and closing a connection per checkout.
os.environ["DB_USE_NULL_POOL"] = "true"

import asyncpg  # noqa: E402
import pytest  # noqa: E402
import pytest_asyncio  # noqa: E402
from alembic import command  # noqa: E402
from alembic.config import Config  # noqa: E402
from httpx import ASGITransport, AsyncClient  # noqa: E402
from sqlalchemy import text  # noqa: E402
from sqlalchemy.ext.asyncio import AsyncSession  # noqa: E402

from app.core.config import settings  # noqa: E402
from app.db.session import SessionLocal, engine  # noqa: E402
from app.main import app  # noqa: E402

_PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


async def _admin_execute(statement: str) -> None:
    """Run a statement against the maintenance database.

    CREATE/DROP DATABASE cannot run inside a transaction, so this uses a raw
    asyncpg connection rather than the application engine.
    """
    conn = await asyncpg.connect(
        user=settings.POSTGRES_USER,
        password=settings.POSTGRES_PASSWORD,
        host=settings.POSTGRES_HOST,
        port=settings.POSTGRES_PORT,
        database=_ADMIN_DB,
    )
    try:
        await conn.execute(statement)
    finally:
        await conn.close()


@pytest.fixture(scope="session", autouse=True)
def prepared_database() -> None:
    """Create the test database, migrate it, and drop it afterwards.

    Synchronous on purpose: Alembic's env.py calls ``asyncio.run`` internally,
    which would fail if invoked from inside a running event loop.
    """
    asyncio.run(_admin_execute(f'DROP DATABASE IF EXISTS "{_TEST_DB}" WITH (FORCE)'))
    asyncio.run(_admin_execute(f'CREATE DATABASE "{_TEST_DB}"'))

    alembic_cfg = Config(os.path.join(_PROJECT_ROOT, "alembic.ini"))
    alembic_cfg.set_main_option("script_location", os.path.join(_PROJECT_ROOT, "alembic"))
    command.upgrade(alembic_cfg, "head")

    yield

    asyncio.run(engine.dispose())
    asyncio.run(_admin_execute(f'DROP DATABASE IF EXISTS "{_TEST_DB}" WITH (FORCE)'))


@pytest_asyncio.fixture(autouse=True)
async def clean_tables() -> None:
    """Give every test empty tables.

    RESTART IDENTITY resets the order and trade sequences so ids are
    predictable per test; CASCADE handles the trades -> orders foreign key.
    """
    async with SessionLocal() as session:
        await session.execute(
            text(
                "TRUNCATE TABLE portfolio_snapshots, trades, orders, positions, wallet "
                "RESTART IDENTITY CASCADE"
            )
        )
        await session.commit()
    yield


@pytest_asyncio.fixture
async def session() -> AsyncSession:
    """A session for tests that exercise the service layer directly."""
    async with SessionLocal() as db_session:
        yield db_session


@pytest_asyncio.fixture
async def client() -> AsyncClient:
    """HTTP client wired straight to the ASGI app — no network involved."""
    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test"
    ) as async_client:
        yield async_client
