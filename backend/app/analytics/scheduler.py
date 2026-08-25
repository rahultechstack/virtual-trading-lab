"""Periodic snapshot job.

Runs on APScheduler alongside the price poller. It owns its own database
session because it runs outside any request.

The mark price is obtained as cheaply as possible: the live stream's most
recent tick is reused when it is fresh, and the provider is only queried when
it is not. When the position is flat no price is needed at all, so nothing is
fetched.
"""

from datetime import UTC, datetime
from decimal import Decimal

from apscheduler.schedulers.asyncio import AsyncIOScheduler
from sqlalchemy import select

from app.analytics.snapshots import SnapshotService
from app.core.config import settings
from app.core.exceptions import WalletNotFoundError
from app.core.logging import get_logger
from app.db.session import SessionLocal
from app.models.portfolio_snapshot import SnapshotSource
from app.models.trading import Position

logger = get_logger(__name__)

_JOB_ID = "portfolio-snapshot"

_scheduler: AsyncIOScheduler | None = None


async def _current_mark_price() -> Decimal | None:
    """Latest price, reusing the stream's tick when it is recent enough."""
    from app.realtime.price_stream import get_price_stream

    stream = get_price_stream()
    tick = stream.last_tick

    if tick is not None:
        server_time = tick["data"].get("server_time")
        try:
            age = (
                datetime.now(tz=UTC) - datetime.fromisoformat(server_time)
            ).total_seconds()
        except (TypeError, ValueError):
            age = None

        if age is not None and age <= settings.SNAPSHOT_INTERVAL_SECONDS:
            return Decimal(tick["data"]["last_price"])

    from app.market_data.registry import get_provider

    quote = await get_provider().get_current_quote(
        settings.TRADING_SYMBOL, settings.TRADING_EXCHANGE
    )
    return quote.last_price


async def capture_periodic_snapshot() -> None:
    """One scheduled capture. Never raises -- the scheduler must keep running."""
    try:
        async with SessionLocal() as session:
            position = (
                await session.execute(
                    select(Position).where(Position.symbol == settings.TRADING_SYMBOL)
                )
            ).scalar_one_or_none()

            # Only pay for a price when there is a position to value.
            mark_price = None
            if position is not None and position.quantity != 0:
                mark_price = await _current_mark_price()

            snapshot = await SnapshotService(session).capture(
                mark_price=mark_price,
                source=SnapshotSource.PERIODIC,
                skip_if_unchanged=settings.SNAPSHOT_SKIP_UNCHANGED,
            )

        if snapshot is not None:
            logger.debug(
                "Snapshot captured: total=%s net=%s",
                snapshot.total_value,
                snapshot.net_pnl,
            )
    except WalletNotFoundError:
        # Nothing to snapshot until the wallet exists.
        return
    except Exception as exc:  # noqa: BLE001 - a failed snapshot must not stop the job
        logger.warning("Periodic snapshot failed: %s", exc)


def start_snapshot_scheduler() -> None:
    """Begin taking periodic snapshots."""
    global _scheduler
    if _scheduler is not None or not settings.SNAPSHOT_ENABLED:
        return

    _scheduler = AsyncIOScheduler(timezone="UTC")
    _scheduler.add_job(
        capture_periodic_snapshot,
        trigger="interval",
        seconds=settings.SNAPSHOT_INTERVAL_SECONDS,
        id=_JOB_ID,
        max_instances=1,
        coalesce=True,
        misfire_grace_time=int(settings.SNAPSHOT_INTERVAL_SECONDS),
    )
    _scheduler.start()
    logger.info(
        "Portfolio snapshots every %ss.", settings.SNAPSHOT_INTERVAL_SECONDS
    )


async def stop_snapshot_scheduler() -> None:
    global _scheduler
    if _scheduler is not None:
        _scheduler.shutdown(wait=False)
        _scheduler = None
