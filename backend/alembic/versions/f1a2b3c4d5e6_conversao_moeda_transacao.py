"""Conversão de moeda: original congelado por lançamento

Lançamento em moeda estrangeira é convertido para BRL na entrada (PTAX do dia +
IOF). total_amount/currency ficam em BRL; as colunas abaixo guardam o original.

Revision ID: f1a2b3c4d5e6
Revises: e5a1b9c3d720
Create Date: 2026-07-23
"""
from alembic import op
import sqlalchemy as sa

revision = 'f1a2b3c4d5e6'
down_revision = 'e5a1b9c3d720'
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Idempotente (ADR 0005): DDL do SQLite não é transacional
    inspector = sa.inspect(op.get_bind())
    cols = {c['name'] for c in inspector.get_columns('transaction')}
    if 'original_amount' not in cols:
        op.add_column('transaction', sa.Column('original_amount', sa.Numeric(20, 2), nullable=True))
    if 'original_currency' not in cols:
        op.add_column('transaction', sa.Column('original_currency', sa.String(), nullable=True))
    if 'exchange_rate' not in cols:
        op.add_column('transaction', sa.Column('exchange_rate', sa.Numeric(20, 6), nullable=True))
    if 'iof_rate' not in cols:
        op.add_column('transaction', sa.Column('iof_rate', sa.Numeric(8, 6), nullable=True))


def downgrade() -> None:
    op.drop_column('transaction', 'iof_rate')
    op.drop_column('transaction', 'exchange_rate')
    op.drop_column('transaction', 'original_currency')
    op.drop_column('transaction', 'original_amount')
