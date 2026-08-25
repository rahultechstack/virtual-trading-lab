"""create wallet table

Creates the single virtual trading account. The ``ck_wallet_singleton``
constraint pins the primary key to 1 so a second wallet cannot be inserted.

Revision ID: ea97efd67efb
Revises: 
Create Date: 2026-08-25 09:12:39.370251
"""

from collections.abc import Sequence

from alembic import op
import sqlalchemy as sa


revision: str = 'ea97efd67efb'
down_revision: str | None = None
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table('wallet',
    sa.Column('id', sa.Integer(), autoincrement=False, nullable=False),
    sa.Column('currency', sa.String(length=3), nullable=False),
    sa.Column('initial_balance', sa.Numeric(precision=18, scale=2), nullable=False),
    sa.Column('cash_balance', sa.Numeric(precision=18, scale=2), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.CheckConstraint('cash_balance >= 0', name=op.f('ck_wallet_cash_balance_non_negative')),
    sa.CheckConstraint('id = 1', name=op.f('ck_wallet_singleton')),
    sa.CheckConstraint('initial_balance > 0', name=op.f('ck_wallet_initial_balance_positive')),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_wallet'))
    )


def downgrade() -> None:
    op.drop_table('wallet')
