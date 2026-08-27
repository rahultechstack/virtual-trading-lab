"""multi-instrument portfolio snapshots

The platform now trades any instrument in the supported universe against one
wallet, so a snapshot describes the **portfolio**, not a single stock.

``portfolio_snapshots.symbol`` becomes nullable: it names the instrument only
when exactly one position is open. With none or several open, no single symbol
describes the row, and the aggregate columns (cash, position_value,
total_value, realized/unrealized/net P&L) carry the whole account.

Existing rows are untouched -- they were all single-instrument and remain
correct as written.

No other table needs changing: orders, trades, positions and automatic_orders
already carry ``symbol``, and ``positions`` is already keyed by it.

Revision ID: 9f2b6c31ae74
Revises: 7c4e1a9b2d55
Create Date: 2026-08-28 09:00:00.000000
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "9f2b6c31ae74"
down_revision: str | None = "7c4e1a9b2d55"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.alter_column(
        "portfolio_snapshots",
        "symbol",
        existing_type=sa.String(length=32),
        nullable=True,
    )


def downgrade() -> None:
    # A portfolio-wide row has no symbol to restore, so backfill with the
    # configured default before re-imposing NOT NULL -- otherwise the downgrade
    # fails on any multi-instrument history.
    op.execute(
        "UPDATE portfolio_snapshots SET symbol = 'PORTFOLIO' WHERE symbol IS NULL"
    )
    op.alter_column(
        "portfolio_snapshots",
        "symbol",
        existing_type=sa.String(length=32),
        nullable=False,
    )
