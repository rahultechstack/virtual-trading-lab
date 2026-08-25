"""create orders, trades and positions

The trading schema. Native PostgreSQL enums are created for order side, status
and type so the database rejects an invalid value on its own.

The three enum types are created explicitly with ``checkfirst`` and dropped
explicitly on downgrade. Left to autogenerate, ``order_side`` would be emitted
once per table that uses it (orders and trades), and a downgrade would leave
the types behind so that re-upgrading failed with DuplicateObjectError.

Revision ID: 44b98124fbd4
Revises: ea97efd67efb
Create Date: 2026-08-25 09:56:13.153391
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "44b98124fbd4"
down_revision: str | None = "ea97efd67efb"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


# create_type=False: the types are created once, up front, by upgrade().
order_side = postgresql.ENUM(
    "BUY",
    "SELL",
    "SHORT_SELL",
    "BUY_TO_COVER",
    name="order_side",
    create_type=False,
)
order_status = postgresql.ENUM(
    "PENDING",
    "FILLED",
    "REJECTED",
    "CANCELLED",
    name="order_status",
    create_type=False,
)
order_type = postgresql.ENUM("MARKET", name="order_type", create_type=False)


def upgrade() -> None:
    bind = op.get_bind()
    order_side.create(bind, checkfirst=True)
    order_status.create(bind, checkfirst=True)
    order_type.create(bind, checkfirst=True)

    op.create_table(
        "orders",
        sa.Column("id", sa.BigInteger(), autoincrement=True, nullable=False),
        sa.Column("symbol", sa.String(length=32), nullable=False),
        sa.Column("exchange", sa.String(length=16), nullable=False),
        sa.Column("side", order_side, nullable=False),
        sa.Column("order_type", order_type, nullable=False),
        sa.Column("quantity", sa.Integer(), nullable=False),
        sa.Column("requested_price", sa.Numeric(precision=18, scale=2), nullable=True),
        sa.Column("execution_price", sa.Numeric(precision=18, scale=2), nullable=True),
        sa.Column("status", order_status, nullable=False),
        sa.Column("rejection_reason", sa.String(length=500), nullable=True),
        sa.Column("filled_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.CheckConstraint(
            "status <> 'FILLED' OR execution_price IS NOT NULL",
            name=op.f("ck_orders_filled_orders_have_a_price"),
        ),
        sa.CheckConstraint(
            "execution_price IS NULL OR execution_price > 0",
            name=op.f("ck_orders_execution_price_positive"),
        ),
        sa.CheckConstraint(
            "quantity <= 10000000", name=op.f("ck_orders_quantity_within_bounds")
        ),
        sa.CheckConstraint("quantity > 0", name=op.f("ck_orders_quantity_positive")),
        sa.CheckConstraint(
            "requested_price IS NULL OR requested_price > 0",
            name=op.f("ck_orders_requested_price_positive"),
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_orders")),
    )
    op.create_index("ix_orders_created_at", "orders", ["created_at"], unique=False)
    op.create_index(op.f("ix_orders_status"), "orders", ["status"], unique=False)
    op.create_index(op.f("ix_orders_symbol"), "orders", ["symbol"], unique=False)

    op.create_table(
        "positions",
        sa.Column("symbol", sa.String(length=32), nullable=False),
        sa.Column("exchange", sa.String(length=16), nullable=False),
        sa.Column("quantity", sa.Integer(), nullable=False),
        sa.Column("average_price", sa.Numeric(precision=18, scale=4), nullable=False),
        sa.Column("realized_pnl", sa.Numeric(precision=18, scale=2), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.CheckConstraint(
            "(quantity = 0 AND average_price = 0) OR "
            "(quantity <> 0 AND average_price > 0)",
            name=op.f("ck_positions_average_price_matches_quantity"),
        ),
        sa.CheckConstraint(
            "average_price >= 0", name=op.f("ck_positions_average_price_non_negative")
        ),
        sa.PrimaryKeyConstraint("symbol", name=op.f("pk_positions")),
    )

    op.create_table(
        "trades",
        sa.Column("id", sa.BigInteger(), autoincrement=True, nullable=False),
        sa.Column("order_id", sa.BigInteger(), nullable=False),
        sa.Column("symbol", sa.String(length=32), nullable=False),
        sa.Column("exchange", sa.String(length=16), nullable=False),
        sa.Column("side", order_side, nullable=False),
        sa.Column("quantity", sa.Integer(), nullable=False),
        sa.Column("execution_price", sa.Numeric(precision=18, scale=2), nullable=False),
        sa.Column("realized_pnl", sa.Numeric(precision=18, scale=2), nullable=False),
        sa.Column("closed_quantity", sa.Integer(), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.CheckConstraint(
            "execution_price > 0", name=op.f("ck_trades_execution_price_positive")
        ),
        sa.CheckConstraint("quantity > 0", name=op.f("ck_trades_quantity_positive")),
        sa.ForeignKeyConstraint(
            ["order_id"],
            ["orders.id"],
            name=op.f("fk_trades_order_id_orders"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_trades")),
    )
    op.create_index("ix_trades_created_at", "trades", ["created_at"], unique=False)
    op.create_index(op.f("ix_trades_order_id"), "trades", ["order_id"], unique=False)
    op.create_index(op.f("ix_trades_symbol"), "trades", ["symbol"], unique=False)


def downgrade() -> None:
    op.drop_index(op.f("ix_trades_symbol"), table_name="trades")
    op.drop_index(op.f("ix_trades_order_id"), table_name="trades")
    op.drop_index("ix_trades_created_at", table_name="trades")
    op.drop_table("trades")

    op.drop_table("positions")

    op.drop_index(op.f("ix_orders_symbol"), table_name="orders")
    op.drop_index(op.f("ix_orders_status"), table_name="orders")
    op.drop_index("ix_orders_created_at", table_name="orders")
    op.drop_table("orders")

    # Drop the types too, so upgrading again after a downgrade works.
    bind = op.get_bind()
    order_type.drop(bind, checkfirst=True)
    order_status.drop(bind, checkfirst=True)
    order_side.drop(bind, checkfirst=True)
