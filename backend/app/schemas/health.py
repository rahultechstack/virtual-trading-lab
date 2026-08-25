"""Response contracts for the health endpoints.

These mirror ``frontend/src/types/health.ts`` — keep both in sync.
"""

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, Field

ServiceStatus = Literal["ok", "degraded", "error"]


class DatabaseHealth(BaseModel):
    status: ServiceStatus = Field(description="Connectivity status of PostgreSQL.")
    detail: str = Field(description="Human-readable diagnostic message.")
    latency_ms: float | None = Field(
        default=None, description="Round-trip time of the probe query."
    )


class HealthResponse(BaseModel):
    status: ServiceStatus
    app_name: str
    version: str
    environment: str
    timestamp: datetime
    database: DatabaseHealth


class PingResponse(BaseModel):
    """Cheapest possible liveness probe — touches no dependency."""

    message: Literal["pong"] = "pong"
    timestamp: datetime
