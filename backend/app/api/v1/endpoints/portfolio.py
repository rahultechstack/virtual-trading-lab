"""Portfolio history and performance endpoints -- transport only."""

from datetime import datetime
from decimal import Decimal
from typing import Annotated

from fastapi import APIRouter, Query, status

from app.analytics.performance import PerformanceAnalyzer
from app.analytics.snapshots import SnapshotService
from app.api.deps import DbSession
from app.models.portfolio_snapshot import SnapshotSource
from app.schemas.portfolio import (
    PerformanceResponse,
    SnapshotResponse,
    SnapshotSeriesResponse,
)

router = APIRouter(prefix="/portfolio", tags=["portfolio"])


@router.get(
    "/snapshots",
    response_model=SnapshotSeriesResponse,
    summary="Portfolio history",
)
async def list_snapshots(
    session: DbSession,
    start: Annotated[
        datetime | None, Query(description="Window start (ISO 8601).")
    ] = None,
    end: Annotated[datetime | None, Query(description="Window end (ISO 8601).")] = None,
    limit: Annotated[int, Query(ge=1, le=5000)] = 500,
    source: Annotated[
        SnapshotSource | None, Query(description="Filter by how it was captured.")
    ] = None,
) -> SnapshotSeriesResponse:
    """The equity curve, oldest first.

    A narrow ``limit`` returns the most recent slice, not the oldest, so a
    default request shows current history rather than ancient history.
    """
    snapshots = await SnapshotService(session).history(
        start=start, end=end, limit=limit, source=source
    )

    return SnapshotSeriesResponse(
        count=len(snapshots),
        first_captured_at=snapshots[0].captured_at if snapshots else None,
        last_captured_at=snapshots[-1].captured_at if snapshots else None,
        snapshots=[SnapshotResponse.model_validate(row) for row in snapshots],
    )


@router.post(
    "/snapshots",
    response_model=SnapshotResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Capture a snapshot now",
    responses={404: {"description": "Wallet has not been initialised."}},
)
async def capture_snapshot(
    session: DbSession,
    mark_price: Annotated[
        Decimal | None,
        Query(gt=0, description="Price to value an open position at."),
    ] = None,
) -> SnapshotResponse:
    """Record the account's value right now.

    Without ``mark_price`` an open position cannot be valued, so the snapshot
    records the cash side only.
    """
    snapshot = await SnapshotService(session).capture(
        mark_price=mark_price, source=SnapshotSource.MANUAL
    )
    return SnapshotResponse.model_validate(snapshot)


@router.get(
    "/performance",
    response_model=PerformanceResponse,
    summary="Performance summary",
)
async def performance_summary(session: DbSession) -> PerformanceResponse:
    """Aggregate performance across the whole trade history.

    Wins and losses count *closing* fills only, judged on net P&L.
    """
    summary = await PerformanceAnalyzer(session).summary()
    return PerformanceResponse.model_validate(summary)
