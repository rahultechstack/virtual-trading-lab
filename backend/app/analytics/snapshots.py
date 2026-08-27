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
from app.trading.pnl import to_money
from app.trading.portfolio import value_portfolio

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
        mark_prices: dict[str, Decimal] | None = None,
        symbol: str | None = None,
        source: SnapshotSource = SnapshotSource.MANUAL,
        skip_if_unchanged: bool = False,
        commit: bool = True,
    ) -> PortfolioSnapshot | None:
        """Record the whole account's value across every instrument held.

        Args:
            mark_prices: symbol -> price. The general form for a multi-stock
                portfolio.
            mark_price: convenience for one instrument; applied to ``symbol``,
                or to the default instrument when that is omitted. Ignored when
                ``mark_prices`` is supplied.
            symbol: which instrument ``mark_price`` refers to.
            source: why the snapshot is being taken.
            skip_if_unchanged: return ``None`` instead of writing a row
                identical to the previous one, so an idle account does not
                accumulate duplicates.
            commit: False to enrol in the caller's transaction -- the trading
                engine writes its snapshot inside the order's own transaction
                so the two can never disagree.

        Cash and every P&L figure are summed across **all** instruments. An
        open position with no mark price contributes zero, the same rule the
        rest of the engine follows: prices are supplied, never fetched.

        ``symbol``/``quantity``/``average_price``/``mark_price`` on the row
        describe the position only when exactly one is open; with none or
        several they are null/zero, because no single symbol describes a
        portfolio.

        Returns the snapshot, or ``None`` when it was suppressed as unchanged.
        """
        wallet = await self._wallets.get()
        if wallet is None:
            raise WalletNotFoundError()

        marks = dict(mark_prices or {})
        if not marks and mark_price is not None:
            marks[(symbol or settings.TRADING_SYMBOL).upper()] = mark_price

        positions = list(
            (await self._session.execute(select(Position))).scalars().all()
        )
        valuation = value_portfolio(
            wallet=wallet, positions=positions, mark_prices=marks
        )

        open_positions = [p for p in valuation.positions if p.quantity != 0]
        single = open_positions[0] if len(open_positions) == 1 else None

        snapshot = PortfolioSnapshot(
            captured_at=datetime.now(tz=UTC),
            source=source,
            symbol=single.symbol if single else None,
            quantity=single.quantity if single else 0,
            average_price=single.average_price if single else Decimal("0.0000"),
            mark_price=single.mark_price if single else None,
            cash=valuation.cash_balance,
            position_value=valuation.position_value,
            total_value=to_money(valuation.cash_balance + valuation.position_value),
            realized_pnl=valuation.realized_pnl,
            total_charges=valuation.total_charges,
            unrealized_pnl=valuation.unrealized_pnl,
            net_pnl=to_money(valuation.net_realized_pnl + valuation.unrealized_pnl),
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
