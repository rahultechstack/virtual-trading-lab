"""add portfolio snapshots

Adds the append-only equity-curve history table.

Also aligns three columns whose server defaults existed only on one side:
``positions.realized_pnl``, ``trades.gross_pnl`` and ``trades.closed_quantity``
now carry the same default in the database as in the model, so autogenerate
stops reporting phantom drift on every future migration.

As in the trading-schema migration, the ``snapshot_source`` enum is created
and dropped explicitly rather than left to ``create_table``, so a downgrade
does not strand the type and break the next upgrade.

Revision ID: 51917e5fa5f1
Revises: b41705c11d09
Create Date: 2026-08-25 11:19:06.462925
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "51917e5fa5f1"
down_revision: str | None = "b41705c11d09"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

MONEY = sa.Numeric(precision=18, scale=2)

# create_type=False: the type is created once, up front, by upgrade().
snapshot_source = postgresql.ENUM(
    "PERIODIC", "TRADE", "MANUAL", name="snapshot_source", create_type=False
)


def upgrade() -> None:
    bind = op.get_bind()
    snapshot_source.create(bind, checkfirst=True)

    op.create_table(
        "portfolio_snapshots",
        sa.Column("id", sa.BigInteger(), autoincrement=True, nullable=False),
        sa.Column(
            "captured_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column("source", snapshot_source, nullable=False),
        sa.Column("symbol", sa.String(length=32), nullable=False),
        sa.Column("quantity", sa.Integer(), nullable=False),
        sa.Column("average_price", sa.Numeric(precision=18, scale=4), nullable=False),
        sa.Column("mark_price", MONEY, nullable=True),
        sa.Column("cash", MONEY, nullable=False),
        sa.Column("position_value", MONEY, nullable=False),
        sa.Column("total_value", MONEY, nullable=False),
        sa.Column("realized_pnl", MONEY, nullable=False),
        sa.Column("total_charges", MONEY, nullable=False),
        sa.Column("unrealized_pnl", MONEY, nullable=False),
        sa.Column("net_pnl", MONEY, nullable=False),
        sa.CheckConstraint(
            "cash >= 0", name=op.f("ck_portfolio_snapshots_cash_non_negative")
        ),
        sa.CheckConstraint(
            "mark_price IS NULL OR mark_price > 0",
            name=op.f("ck_portfolio_snapshots_mark_price_positive"),
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_portfolio_snapshots")),
    )
    op.create_index(
        "ix_portfolio_snapshots_captured_at",
        "portfolio_snapshots",
        ["captured_at"],
        unique=False,
    )
    op.create_index(
        op.f("ix_portfolio_snapshots_source"),
        "portfolio_snapshots",
        ["source"],
        unique=False,
    )

    # Bring these defaults into line with the models.
    op.alter_column(
        "positions",
        "realized_pnl",
        existing_type=sa.NUMERIC(precision=18, scale=2),
        server_default=sa.text("0"),
        existing_nullable=False,
    )
    op.alter_column(
        "trades",
        "gross_pnl",
        existing_type=sa.NUMERIC(precision=18, scale=2),
        server_default=sa.text("0"),
        existing_nullable=False,
    )
    op.alter_column(
        "trades",
        "closed_quantity",
        existing_type=sa.INTEGER(),
        server_default=sa.text("0"),
        existing_nullable=False,
    )


def downgrade() -> None:
    op.alter_column(
        "trades",
        "closed_quantity",
        existing_type=sa.INTEGER(),
        server_default=None,
        existing_nullable=False,
    )
    op.alter_column(
        "trades",
        "gross_pnl",
        existing_type=sa.NUMERIC(precision=18, scale=2),
        server_default=None,
        existing_nullable=False,
    )
    op.alter_column(
        "positions",
        "realized_pnl",
        existing_type=sa.NUMERIC(precision=18, scale=2),
        server_default=None,
        existing_nullable=False,
    )

    op.drop_index(op.f("ix_portfolio_snapshots_source"), table_name="portfolio_snapshots")
    op.drop_index(
        "ix_portfolio_snapshots_captured_at", table_name="portfolio_snapshots"
    )
    op.drop_table("portfolio_snapshots")

    # Drop the type too, so upgrading again after a downgrade works.
    snapshot_source.drop(op.get_bind(), checkfirst=True)
