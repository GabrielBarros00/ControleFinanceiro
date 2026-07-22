"""Recorrência com intervalo (a cada N) e âncora start_date

- recurringexpense/recurringincome.interval: multiplicador "a cada N" (default 1)
- recurringexpense/recurringincome.start_date: âncora do intervalo (N>1)

Revision ID: e5a1b9c3d720
Revises: c2f7a91d4e63
Create Date: 2026-07-22
"""
from alembic import op
import sqlalchemy as sa

revision = 'e5a1b9c3d720'
down_revision = 'c2f7a91d4e63'
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Idempotente (ADR 0005): DDL do SQLite não é transacional
    inspector = sa.inspect(op.get_bind())
    for table in ('recurringexpense', 'recurringincome'):
        if table not in inspector.get_table_names():
            continue
        cols = {c['name'] for c in inspector.get_columns(table)}
        if 'interval' not in cols:
            op.add_column(table, sa.Column('interval', sa.Integer(), nullable=False, server_default='1'))
        if 'start_date' not in cols:
            op.add_column(table, sa.Column('start_date', sa.Date(), nullable=True))


def downgrade() -> None:
    for table in ('recurringincome', 'recurringexpense'):
        op.drop_column(table, 'start_date')
        op.drop_column(table, 'interval')
