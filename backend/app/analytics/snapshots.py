"""Portfolio snapshot capture.

Turns the current account state into an append-only history row. The mark
price is always supplied by the caller -- this module never reaches out to a
market-data provider, keeping it usable from a request, a scheduled job or a
test alike.
"""

from datetime import UTC, datetime
from decimal import Decimal

from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.core.exceptions import WalletNotFoundError
from app.core.logging import get_logger
from app.models.portfolio_snapshot import PortfolioSnapshot, SnapshotSource
from app.models.trading import Position
from app.repositories.wallet_repository import WalletRepository
from app.trading.pnl import PnLCalculator, to_money

logger = get_logger(__name__)


class SnapshotService:
    """Captures and reads portfolio history."""

    def __init__(self, session: AsyncSession) -> None:
        self._session = session
        self._wallets = WalletRepository(session)

    # -- capture ---------------------------------------------------------

    async def capture(
        self,
        *,
        mark_price: Decimal | None = None,
        source: SnapshotSource = SnapshotSource.MANUAL,
        skip_if_unchanged: bool = False,
        commit: bool = True,
    ) -> PortfolioSnapshot | None:
        """Record the account's current value.

        Args:
            mark_price: Price to value an open position at. Ignored when flat.
            source: Why the snapshot is being taken.
            skip_if_unchanged: Return ``None`` instead of writing a row
                identical to the previous one. Used by the periodic job so an
                idle account does not accumulate duplicates.
            commit: Set False to enrol in the caller's transaction -- the
                trading engine writes its snapshot inside the order's own
                transaction so the two can never disagree.

        Returns the snapshot, or ``None`` when it was suppressed as unchanged.
        """
        wallet = await self._wallets.get()
        if wallet is None:
            raise WalletNotFoundError()

        position = (
            await self._session.execute(
                select(Position).where(Position.symbol == settings.TRADING_SYMBOL)
            )
        ).scalar_one_or_none()

        quantity = position.quantity if position else 0
        average_price = position.average_price if position else Decimal("0.0000")
        realized = position.realized_pnl if position else Decimal("0.00")
        charges = position.total_charges if position else Decimal("0.00")

        # A flat position needs no mark: there is nothing to value.
        effective_mark = mark_price if quantity != 0 else None

        if effective_mark is None:
            unrealized = Decimal("0.00")
            position_value = Decimal("0.00")
        else:
            unrealized = PnLCalculator.unrealized_pnl(
                quantity=quantity,
                average_price=average_price,
                mark_price=effective_mark,
            )
            position_value = PnLCalculator.position_value(
                quantity=quantity, mark_price=effective_mark
            )

        net_realized = to_money(realized - charges)

        snapshot = PortfolioSnapshot(
            captured_at=datetime.now(tz=UTC),
            source=source,
            symbol=settings.TRADING_SYMBOL,
            quantity=quantity,
            average_price=average_price,
            mark_price=effective_mark,
            cash=wallet.cash_balance,
            position_value=position_value,
            total_value=to_money(wallet.cash_balance + position_value),
            realized_pnl=realized,
            total_charges=charges,
            unrealized_pnl=unrealized,
            net_pnl=to_money(net_realized + unrealized),
        )

        if skip_if_unchanged:
            latest = await self.latest()
            if snapshot.is_equivalent_to(latest):
                return None

        self._session.add(snapshot)
        await self._session.flush()
        if commit:
            await self._session.commit()
            await self._session.refresh(snapshot)
        return snapshot

    # -- reads -----------------------------------------------------------

    async def latest(self) -> PortfolioSnapshot | None:
        result = await self._session.execute(
            select(PortfolioSnapshot)
            .order_by(PortfolioSnapshot.captured_at.desc(), PortfolioSnapshot.id.desc())
            .limit(1)
        )
        return result.scalar_one_or_none()

    async def history(
        self,
        *,
        start: datetime | None = None,
        end: datetime | None = None,
        limit: int = 500,
        source: SnapshotSource | None = None,
    ) -> list[PortfolioSnapshot]:
        """Snapshots oldest first, so the result plots directly as a curve.

        The window is applied before the limit and the most recent rows are
        kept, so a narrow limit returns the latest slice rather than the
        oldest.
        """
        query = select(PortfolioSnapshot)
        if start is not None:
            query = query.where(PortfolioSnapshot.captured_at >= start)
        if end is not None:
            query = query.where(PortfolioSnapshot.captured_at <= end)
        if source is not None:
            query = query.where(PortfolioSnapshot.source == source)

        query = query.order_by(
            PortfolioSnapshot.captured_at.desc(), PortfolioSnapshot.id.desc()
        ).limit(limit)

        rows = list((await self._session.execute(query)).scalars().all())
        rows.reverse()
        return rows

    async def count(self) -> int:
        from sqlalchemy import func

        result = await self._session.execute(
            select(func.count(PortfolioSnapshot.id))
        )
        return int(result.scalar_one())

    async def purge(self) -> int:
        """Delete every snapshot. Used when the account is reset."""
        result = await self._session.execute(delete(PortfolioSnapshot))
        await self._session.commit()
        return int(result.rowcount or 0)
