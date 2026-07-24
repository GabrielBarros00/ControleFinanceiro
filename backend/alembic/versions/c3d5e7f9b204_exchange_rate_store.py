"""Store local de taxas de câmbio (exchangerate)

Revision ID: c3d5e7f9b204
Revises: b2c4e6f8a103
Create Date: 2026-07-24
"""
from alembic import op
import sqlalchemy as sa

revision = 'c3d5e7f9b204'
down_revision = 'b2c4e6f8a103'
branch_labels = None
depends_on = None


def upgrade() -> None:
    inspector = sa.inspect(op.get_bind())
    if 'exchangerate' in inspector.get_table_names():
        return
    op.create_table(
        'exchangerate',
        sa.Column('id', sa.Integer(), primary_key=True, nullable=False),
        sa.Column('currency', sa.String(), nullable=False),
        sa.Column('rate_date', sa.Date(), nullable=False),
        sa.Column('rate', sa.Numeric(20, 6), nullable=False),
        sa.Column('source', sa.String(), nullable=False),
        sa.Column('created_at', sa.DateTime(), nullable=False),
        sa.UniqueConstraint('currency', 'rate_date', name='uq_exchange_rate_currency_date'),
    )
    op.create_index('ix_exchangerate_currency', 'exchangerate', ['currency'])
    op.create_index('ix_exchangerate_rate_date', 'exchangerate', ['rate_date'])


def downgrade() -> None:
    op.drop_index('ix_exchangerate_rate_date', table_name='exchangerate')
    op.drop_index('ix_exchangerate_currency', table_name='exchangerate')
    op.drop_table('exchangerate')
