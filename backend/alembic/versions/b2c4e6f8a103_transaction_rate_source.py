"""Fonte da taxa de câmbio por lançamento (ptax/market)

Revision ID: b2c4e6f8a103
Revises: a7b3c9d15e42
Create Date: 2026-07-24
"""
from alembic import op
import sqlalchemy as sa

revision = 'b2c4e6f8a103'
down_revision = 'a7b3c9d15e42'
branch_labels = None
depends_on = None


def upgrade() -> None:
    inspector = sa.inspect(op.get_bind())
    cols = {c['name'] for c in inspector.get_columns('transaction')}
    if 'rate_source' not in cols:
        op.add_column('transaction', sa.Column('rate_source', sa.String(), nullable=True))


def downgrade() -> None:
    op.drop_column('transaction', 'rate_source')
