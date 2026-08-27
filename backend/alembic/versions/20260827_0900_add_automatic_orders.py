"""add automatic orders

Adds the standing-instruction table behind stop-losses and price triggers.

As in the trading-schema and snapshot migrations, the new enum types are
created and dropped **explicitly** with ``checkfirst`` rather than left to
``create_table``. Left to autogenerate they would be emitted once per
referencing column, and a downgrade would strand them so the next upgrade
failed with DuplicateObjectError.

``order_side`` is deliberately *reused* for ``action`` -- a trigger's action is
exactly the side the engine will execute -- so it is referenced with
``create_type=False`` and is NOT dropped on downgrade; the orders and trades
tables still need it.

Revision ID: 7c4e1a9b2d55
Revises: 51917e5fa5f1
Create Date: 2026-08-27 09:00:00.000000
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "7c4e1a9b2d55"
down_revision: str | None = "51917e5fa5f1"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

MONEY = sa.Numeric(precision=18, scale=2)

MAX_ORDER_QUANTITY = 10_000_000

# create_type=False: created once, up front, by upgrade().
automatic_order_type = postgresql.ENUM(
    "STOP_LOSS", "PRICE_TRIGGER", name="automatic_order_type", create_type=False
)
trigger_condition = postgresql.ENUM(
    "GTE", "LTE", name="trigger_condition", create_type=False
)
automatic_order_status = postgresql.ENUM(
    "ACTIVE",
    "TRIGGERED",
    "CANCELLED",
    "FAILED",
    name="automatic_order_status",
    create_type=False,
)
# Already exists (orders, trades). Referenced, never created or dropped here.
order_side = postgresql.ENUM(
    "BUY", "SELL", "SHORT_SELL", "BUY_TO_COVER", name="order_side", create_type=False
)


def upgrade() -> None:
    bind = op.get_bind()
    automatic_order_type.create(bind, checkfirst=True)
    trigger_condition.create(bind, checkfirst=True)
    automatic_order_status.create(bind, checkfirst=True)

    op.create_table(
        "automatic_orders",
        sa.Column("id", sa.BigInteger(), autoincrement=True, nullable=False),
        sa.Column("symbol", sa.String(length=32), nullable=False),
        sa.Column("exchange", sa.String(length=16), nullable=False),
        sa.Column("order_type", automatic_order_type, nullable=False),
        sa.Column("trigger_price", MONEY, nullable=False),
        sa.Column("trigger_condition", trigger_condition, nullable=False),
        sa.Column("action", order_side, nullable=False),
        sa.Column("quantity", sa.Integer(), nullable=False),
        sa.Column("status", automatic_order_status, nullable=False),
        sa.Column("triggered_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("cancelled_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("trigger_market_price", MONEY, nullable=True),
        sa.Column("triggered_order_id", sa.BigInteger(), nullable=True),
        sa.Column("reason", sa.String(length=500), nullable=True),
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
            "quantity > 0", name=op.f("ck_automatic_orders_quantity_positive")
        ),
        sa.CheckConstraint(
            f"quantity <= {MAX_ORDER_QUANTITY}",
            name=op.f("ck_automatic_orders_quantity_within_bounds"),
        ),
        sa.CheckConstraint(
            "trigger_price > 0",
            name=op.f("ck_automatic_orders_trigger_price_positive"),
        ),
        sa.CheckConstraint(
            "status <> 'TRIGGERED' OR triggered_at IS NOT NULL",
            name=op.f("ck_automatic_orders_triggered_orders_have_a_timestamp"),
        ),
        sa.CheckConstraint(
            "status <> 'CANCELLED' OR cancelled_at IS NOT NULL",
            name=op.f("ck_automatic_orders_cancelled_orders_have_a_timestamp"),
        ),
        sa.ForeignKeyConstraint(
            ["triggered_order_id"],
            ["orders.id"],
            name=op.f("fk_automatic_orders_triggered_order_id_orders"),
            ondelete="SET NULL",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_automatic_orders")),
    )

    op.create_index(
        op.f("ix_automatic_orders_symbol"), "automatic_orders", ["symbol"]
    )
    op.create_index(
        op.f("ix_automatic_orders_status"), "automatic_orders", ["status"]
    )
    op.create_index(
        op.f("ix_automatic_orders_triggered_order_id"),
        "automatic_orders",
        ["triggered_order_id"],
    )
    # The monitor scans by (symbol, status) on every tick.
    op.create_index(
        "ix_automatic_orders_symbol_status",
        "automatic_orders",
        ["symbol", "status"],
    )
    op.create_index(
        "ix_automatic_orders_created_at", "automatic_orders", ["created_at"]
    )


def downgrade() -> None:
    op.drop_index("ix_automatic_orders_created_at", table_name="automatic_orders")
    op.drop_index("ix_automatic_orders_symbol_status", table_name="automatic_orders")
    op.drop_index(
        op.f("ix_automatic_orders_triggered_order_id"), table_name="automatic_orders"
    )
    op.drop_index(op.f("ix_automatic_orders_status"), table_name="automatic_orders")
    op.drop_index(op.f("ix_automatic_orders_symbol"), table_name="automatic_orders")
    op.drop_table("automatic_orders")

    bind = op.get_bind()
    automatic_order_status.drop(bind, checkfirst=True)
    trigger_condition.drop(bind, checkfirst=True)
    automatic_order_type.drop(bind, checkfirst=True)
    # order_side is intentionally left in place: orders and trades use it.
