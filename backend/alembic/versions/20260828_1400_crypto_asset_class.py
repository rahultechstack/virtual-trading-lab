"""crypto asset class: fractional quantities, asset identity, TDS

Three changes, all needed to trade a second asset class alongside NSE equities.

**1. Quantities become fractional.** ``Integer`` -> ``Numeric(28, 8)`` on
``orders.quantity``, ``trades.quantity``, ``trades.closed_quantity``,
``positions.quantity`` and ``automatic_orders.quantity``. Crypto trades in
fractions of a unit -- 0.001 BTC is an ordinary size -- and eight decimal
places is one satoshi. Whether a *given* instrument may use those decimals is
enforced by ``Instrument.quantity_step``, not by the column type, so an NSE
equity still trades in whole shares.

The widening is loss-free: every existing integer quantity is exactly
representable. The existing CHECK constraints (``quantity > 0``,
``quantity <= 10000000``) hold unchanged over numeric and are revalidated by
PostgreSQL during the type change.

**2. Every record identifies its asset class.** A new ``asset_class`` enum
column on orders, trades, positions and automatic_orders. All existing rows are
NSE equities, so they backfill to ``STOCK``. This is denormalised on purpose:
history stays readable without a catalogue lookup, and stays correct even if an
instrument is later removed from the catalogue.

**3. Crypto TDS gets its own column.** ``trades.tds`` holds tax withheld at
source on a Virtual Digital Asset transfer. It is neither a broker fee nor STT,
so folding it into an existing column would misreport what was charged.

As in the earlier migrations the new enum type is created and dropped
**explicitly** with ``checkfirst`` rather than left to autogenerate, which would
emit it once per referencing column and strand it on downgrade.

Revision ID: 3d81f0c47b92
Revises: 9f2b6c31ae74
Create Date: 2026-08-28 14:00:00.000000
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "3d81f0c47b92"
down_revision: str | None = "9f2b6c31ae74"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

MONEY = sa.Numeric(precision=18, scale=2)
QUANTITY = sa.Numeric(precision=28, scale=8)

# create_type=False: created once, up front, by upgrade().
asset_class = postgresql.ENUM("STOCK", "CRYPTO", name="asset_class", create_type=False)

#: table -> quantity columns to widen.
_QUANTITY_COLUMNS = {
    "orders": ("quantity",),
    "trades": ("quantity", "closed_quantity"),
    "positions": ("quantity",),
    "automatic_orders": ("quantity",),
    # A snapshot naming a single open position carries its size, so it needs
    # the same widening -- otherwise a snapshot of 0.001 BTC would store 0.
    "portfolio_snapshots": ("quantity",),
}

#: Tables gaining the asset_class column.
_ASSET_CLASS_TABLES = ("orders", "trades", "positions", "automatic_orders")


def upgrade() -> None:
    bind = op.get_bind()

    # 1. Fractional quantities. USING is required: PostgreSQL will not widen
    #    integer to numeric implicitly inside ALTER COLUMN TYPE.
    for table, columns in _QUANTITY_COLUMNS.items():
        for column in columns:
            op.alter_column(
                table,
                column,
                existing_type=sa.Integer(),
                type_=QUANTITY,
                existing_nullable=False,
                postgresql_using=f"{column}::numeric(28,8)",
            )

    # 2. Asset identity on every record.
    asset_class.create(bind, checkfirst=True)
    for table in _ASSET_CLASS_TABLES:
        op.add_column(
            table,
            sa.Column(
                "asset_class",
                asset_class,
                nullable=False,
                # Every pre-existing row is an NSE equity. The server default
                # also backfills them in one pass.
                server_default="STOCK",
            ),
        )
        op.create_index(
            f"ix_{table}_asset_class", table, ["asset_class"], unique=False
        )
        # The application always supplies the value; the default existed only
        # to backfill. Dropping it keeps the app the authority, as it is for
        # `exchange`.
        op.alter_column(table, "asset_class", server_default=None)

    # 3. Crypto TDS.
    op.add_column(
        "trades",
        sa.Column("tds", MONEY, nullable=False, server_default=sa.text("0")),
    )


def downgrade() -> None:
    bind = op.get_bind()

    op.drop_column("trades", "tds")

    for table in _ASSET_CLASS_TABLES:
        op.drop_index(f"ix_{table}_asset_class", table_name=table)
        op.drop_column(table, "asset_class")
    asset_class.drop(bind, checkfirst=True)

    # Narrowing back to integer is LOSSY: any fractional quantity would be
    # silently truncated, turning 0.001 BTC into 0 and corrupting both the
    # position and its P&L. Refuse instead, and say what to do about it.
    for table, columns in _QUANTITY_COLUMNS.items():
        for column in columns:
            fractional = bind.execute(
                sa.text(
                    f"SELECT count(*) FROM {table} "  # noqa: S608 - fixed identifiers
                    f"WHERE {column} <> trunc({column})"
                )
            ).scalar_one()
            if fractional:
                raise RuntimeError(
                    f"Cannot downgrade: {table}.{column} holds {fractional} "
                    "fractional row(s), which an integer column cannot "
                    "represent. Close or delete the crypto positions first, or "
                    "restore from a backup taken before this migration."
                )

    for table, columns in _QUANTITY_COLUMNS.items():
        for column in columns:
            op.alter_column(
                table,
                column,
                existing_type=QUANTITY,
                type_=sa.Integer(),
                existing_nullable=False,
                postgresql_using=f"{column}::integer",
            )
