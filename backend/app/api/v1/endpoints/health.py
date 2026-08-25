"""Health endpoints — transport layer only, logic lives in HealthService."""

from fastapi import APIRouter, status

from app.api.deps import DbSession
from app.schemas.health import HealthResponse, PingResponse
from app.services.health_service import health_service

router = APIRouter(prefix="/health", tags=["health"])


@router.get(
    "/ping",
    response_model=PingResponse,
    status_code=status.HTTP_200_OK,
    summary="Liveness probe",
)
async def ping() -> PingResponse:
    """Returns immediately without touching PostgreSQL."""
    return await health_service.ping()


@router.get(
    "",
    response_model=HealthResponse,
    status_code=status.HTTP_200_OK,
    summary="Readiness probe including database connectivity",
)
async def health(session: DbSession) -> HealthResponse:
    """Reports application metadata plus a live ``SELECT 1`` against PostgreSQL.

    Always returns HTTP 200; inspect ``status`` / ``database.status`` in the body.
    """
    return await health_service.full_health(session)
