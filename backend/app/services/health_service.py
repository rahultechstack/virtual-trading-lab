"""Health-check business logic.

Lives in the service layer so the API layer stays a thin transport shim.
"""

from datetime import datetime, timezone
from time import perf_counter

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.core.logging import get_logger
from app.schemas.health import DatabaseHealth, HealthResponse, PingResponse

logger = get_logger(__name__)


def _now() -> datetime:
    return datetime.now(timezone.utc)


class HealthService:
    """Reports liveness of the application and its backing services."""

    async def ping(self) -> PingResponse:
        return PingResponse(timestamp=_now())

    async def check_database(self, session: AsyncSession) -> DatabaseHealth:
        started = perf_counter()
        try:
            result = await session.execute(text("SELECT 1"))
            result.scalar_one()
        except Exception as exc:  # noqa: BLE001 - health probe must never raise
            logger.warning("Database health probe failed: %s", exc)
            return DatabaseHealth(
                status="error",
                detail=f"{type(exc).__name__}: {exc}",
            )

        elapsed_ms = round((perf_counter() - started) * 1000, 2)
        return DatabaseHealth(
            status="ok",
            detail="PostgreSQL connection established.",
            latency_ms=elapsed_ms,
        )

    async def full_health(self, session: AsyncSession) -> HealthResponse:
        database = await self.check_database(session)
        return HealthResponse(
            status="ok" if database.status == "ok" else "degraded",
            app_name=settings.APP_NAME,
            version=settings.APP_VERSION,
            environment=settings.ENVIRONMENT,
            timestamp=_now(),
            database=database,
        )


health_service = HealthService()
