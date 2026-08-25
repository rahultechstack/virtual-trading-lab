"""add execution costs and net pnl

Adds the realistic-execution columns: the quote a fill was priced against, the
spread and slippage it cost, each statutory charge, and the resulting gross and
net P&L.

Two things autogenerate got wrong and are corrected here:

* ``trades.realized_pnl`` -> ``trades.gross_pnl`` is a **rename**. Autogenerate
  emitted DROP + ADD, which would discard the P&L on every existing trade.
* The new NOT NULL columns need a ``server_default``, or adding them to a table
  that already has rows fails outright.

``positions.net_realized_pnl`` is backfilled from ``realized_pnl``: trades made
before this migration bore no charges, so gross and net are equal for them.

Revision ID: b41705c11d09
Revises: 44b98124fbd4
Create Date: 2026-08-25 10:10:52.667234
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "b41705c11d09"
down_revision: str | None = "44b98124fbd4"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

MONEY = sa.Numeric(precision=18, scale=2)

#: Cost and charge columns added to trades, all defaulting to zero.
_TRADE_COST_COLUMNS = (
    "spread_cost",
    "slippage_cost",
    "brokerage",
    "stt",
    "exchange_charges",
    "sebi_charges",
    "stamp_duty",
    "gst",
    "dp_charges",
    "total_charges",
    "net_pnl",
)

#: Nullable columns recording the quote the fill was priced against.
_TRADE_QUOTE_COLUMNS = ("reference_price", "bid_price", "ask_price")


def upgrade() -> None:
    # -- positions -------------------------------------------------------
    op.add_column(
        "positions",
        sa.Column("total_charges", MONEY, nullable=False, server_default="0"),
    )
    op.add_column(
        "positions",
        sa.Column("net_realized_pnl", MONEY, nullable=False, server_default="0"),
    )
    # Pre-existing positions paid no charges, so net equals gross.
    op.execute("UPDATE positions SET net_realized_pnl = realized_pnl")

    # -- trades ----------------------------------------------------------
    for column in _TRADE_QUOTE_COLUMNS:
        op.add_column("trades", sa.Column(column, MONEY, nullable=True))

    for column in _TRADE_COST_COLUMNS:
        op.add_column(
            "trades", sa.Column(column, MONEY, nullable=False, server_default="0")
        )

    # A rename, not a drop-and-add: keeps the P&L on existing trades.
    op.alter_column("trades", "realized_pnl", new_column_name="gross_pnl")

    # Historical trades bore no charges, so net equals gross.
    op.execute("UPDATE trades SET net_pnl = gross_pnl")


def downgrade() -> None:
    op.alter_column("trades", "gross_pnl", new_column_name="realized_pnl")

    for column in reversed(_TRADE_COST_COLUMNS):
        op.drop_column("trades", column)
    for column in reversed(_TRADE_QUOTE_COLUMNS):
        op.drop_column("trades", column)

    op.drop_column("positions", "net_realized_pnl")
    op.drop_column("positions", "total_charges")
