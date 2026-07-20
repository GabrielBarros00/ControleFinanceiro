"""Onda 4: snapshot da recorrência, occurrence_date e lote de importação

- recurringexpense ganha snapshot (currency/payment_method/category_id/
  payer_user_id/split_snapshot) para materializar despesa COMPLETA (ADR 0012)
- transaction.occurrence_date + unique (recurring, occurrence) — tombstone
  bloqueia recriação por natureza
- importbatch/importrow: lote auditável com fingerprint idempotente (ADR 0008)

Revision ID: a4c8e17b92d5
Revises: d1f6b083a2c4
Create Date: 2026-07-20
"""
from alembic import op
import sqlalchemy as sa

revision = 'a4c8e17b92d5'
down_revision = 'd1f6b083a2c4'
branch_labels = None
depends_on = None

ROW_STATUSES = ('imported', 'ignored', 'duplicate', 'skipped')


def upgrade() -> None:
    # Idempotente: DDL do SQLite não é transacional (ADR 0005) — re-run após
    # falha parcial precisa completar, não quebrar
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    existing_tables = set(inspector.get_table_names())

    # ADD COLUMN direto (sem batch/FK): o SQLite exigiria FK nomeada + rebuild;
    # as FKs de category_id/payer_user_id são declaradas no modelo (create_all)
    # e a integridade é garantida na aplicação (valida categoria/membro)
    rec_cols = {c['name'] for c in inspector.get_columns('recurringexpense')}
    if 'currency' not in rec_cols:
        op.add_column('recurringexpense', sa.Column('currency', sa.String(), nullable=False, server_default='BRL'))
    if 'payment_method' not in rec_cols:
        op.add_column('recurringexpense', sa.Column('payment_method', sa.String(), nullable=True))
    if 'category_id' not in rec_cols:
        op.add_column('recurringexpense', sa.Column('category_id', sa.Integer(), nullable=True))
    if 'payer_user_id' not in rec_cols:
        op.add_column('recurringexpense', sa.Column('payer_user_id', sa.Integer(), nullable=True))
    if 'split_snapshot' not in rec_cols:
        op.add_column('recurringexpense', sa.Column('split_snapshot', sa.JSON(), nullable=True))

    tx_cols = {c['name'] for c in inspector.get_columns('transaction')}
    if 'occurrence_date' not in tx_cols:
        op.add_column('transaction', sa.Column('occurrence_date', sa.Date(), nullable=True))
    # Unique como ÍNDICE (não constraint): evita rebuild da tabela transaction no
    # SQLite. NULLs são distintos → transações comuns não colidem.
    tx_indexes = {ix['name'] for ix in inspector.get_indexes('transaction')}
    if 'uq_recurring_occurrence' not in tx_indexes:
        op.create_index(
            'uq_recurring_occurrence', 'transaction',
            ['recurring_expense_id', 'occurrence_date'], unique=True,
        )

    if 'importbatch' not in existing_tables:
        op.create_table(
            'importbatch',
            sa.Column('id', sa.Integer(), primary_key=True),
            sa.Column('workspace_id', sa.Integer(), sa.ForeignKey('workspace.id'), nullable=False, index=True),
            sa.Column('filename', sa.String(), nullable=True),
            sa.Column('created_by_user_id', sa.Integer(), sa.ForeignKey('user.id'), nullable=True),
            sa.Column('total_rows', sa.Integer(), nullable=False, server_default='0'),
            sa.Column('imported_count', sa.Integer(), nullable=False, server_default='0'),
            sa.Column('ignored_count', sa.Integer(), nullable=False, server_default='0'),
            sa.Column('duplicate_count', sa.Integer(), nullable=False, server_default='0'),
            sa.Column('skipped_count', sa.Integer(), nullable=False, server_default='0'),
            sa.Column('created_at', sa.DateTime(), nullable=False),
        )

    if 'importrow' not in existing_tables:
        op.create_table(
            'importrow',
            sa.Column('id', sa.Integer(), primary_key=True),
            sa.Column('batch_id', sa.Integer(), sa.ForeignKey('importbatch.id'), nullable=False, index=True),
            sa.Column('workspace_id', sa.Integer(), sa.ForeignKey('workspace.id'), nullable=False, index=True),
            sa.Column('line', sa.Integer(), nullable=True),
            sa.Column('title', sa.String(), nullable=False),
            sa.Column('amount', sa.Numeric(20, 2), nullable=False),
            sa.Column('transaction_date', sa.DateTime(), nullable=False),
            sa.Column('fingerprint', sa.String(), nullable=False, index=True),
            sa.Column('status', sa.Enum(*ROW_STATUSES, name='importrowstatus'), nullable=False),
            sa.Column('transaction_id', sa.Integer(), sa.ForeignKey('transaction.id'), nullable=True),
            sa.Column('reason', sa.String(), nullable=True),
            sa.Column('created_at', sa.DateTime(), nullable=False),
        )


def downgrade() -> None:
    op.drop_table('importrow')
    op.drop_table('importbatch')
    op.drop_index('uq_recurring_occurrence', table_name='transaction')
    op.drop_column('transaction', 'occurrence_date')
    with op.batch_alter_table('recurringexpense') as batch:
        batch.drop_column('split_snapshot')
        batch.drop_column('payer_user_id')
        batch.drop_column('category_id')
        batch.drop_column('payment_method')
        batch.drop_column('currency')
