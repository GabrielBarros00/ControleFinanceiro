"""Conversão de moeda na renda (original congelado)

Renda em moeda estrangeira (inclusive recorrente) é convertida para BRL; guarda
o original. Recorrência re-converte a cada mês na materialização.

Revision ID: d4e6f8a0c315
Revises: c3d5e7f9b204
Create Date: 2026-07-24
"""
from alembic import op
import sqlalchemy as sa

revision = 'd4e6f8a0c315'
down_revision = 'c3d5e7f9b204'
branch_labels = None
depends_on = None


def upgrade() -> None:
    inspector = sa.inspect(op.get_bind())
    cols = {c['name'] for c in inspector.get_columns('income')}
    if 'original_amount' not in cols:
        op.add_column('income', sa.Column('original_amount', sa.Numeric(20, 2), nullable=True))
    if 'original_currency' not in cols:
        op.add_column('income', sa.Column('original_currency', sa.String(), nullable=True))
    if 'exchange_rate' not in cols:
        op.add_column('income', sa.Column('exchange_rate', sa.Numeric(20, 6), nullable=True))
    if 'rate_source' not in cols:
        op.add_column('income', sa.Column('rate_source', sa.String(), nullable=True))


def downgrade() -> None:
    op.drop_column('income', 'rate_source')
    op.drop_column('income', 'exchange_rate')
    op.drop_column('income', 'original_currency')
    op.drop_column('income', 'original_amount')
