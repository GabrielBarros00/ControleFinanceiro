"""Onda 2: contas/carteiras, origem por pagador e ajustes de total

- paymentaccount: de qual conta/carteira saiu o dinheiro (ADR 0004)
- transactionpayer.account_id + payment_method tipado; backfill do método
  global da transação (o campo por pagador era legado sem uso)
- transactionadjustment: total = soma(itens) + soma(ajustes)

Revision ID: c7e4a95d63f1
Revises: b3d9f82c41e7
Create Date: 2026-07-19
"""
from alembic import op
import sqlalchemy as sa

revision = 'c7e4a95d63f1'
down_revision = 'b3d9f82c41e7'
branch_labels = None
depends_on = None

ACCOUNT_TYPES = ('cash', 'checking', 'savings', 'digital_wallet', 'other')
ADJUSTMENT_TYPES = ('discount', 'tax', 'tip', 'shipping', 'cashback', 'rounding', 'other')


def upgrade() -> None:
    # Idempotente por segurança: DDL do SQLite não é transacional — uma falha
    # no meio deixa o banco parcial e o re-run precisa completar, não quebrar
    inspector = sa.inspect(op.get_bind())
    existing_tables = set(inspector.get_table_names())

    if 'paymentaccount' not in existing_tables:
        op.create_table(
            'paymentaccount',
            sa.Column('id', sa.Integer(), primary_key=True),
            sa.Column('workspace_id', sa.Integer(), sa.ForeignKey('workspace.id'), nullable=False, index=True),
            sa.Column('owner_user_id', sa.Integer(), sa.ForeignKey('user.id'), nullable=True),
            sa.Column('name', sa.String(), nullable=False, index=True),
            sa.Column('type', sa.Enum(*ACCOUNT_TYPES, name='paymentaccounttype'), nullable=False, server_default='checking'),
            sa.Column('currency', sa.String(), nullable=False, server_default='BRL'),
            sa.Column('active', sa.Boolean(), nullable=False, server_default=sa.true()),
            sa.Column('created_at', sa.DateTime(), nullable=False),
            sa.Column('updated_at', sa.DateTime(), nullable=False),
            sa.Column('deleted_at', sa.DateTime(), nullable=True),
            sa.UniqueConstraint('workspace_id', 'name', name='uq_paymentaccount_workspace_name'),
        )

    payer_cols = {c['name'] for c in inspector.get_columns('transactionpayer')}
    if 'account_id' not in payer_cols:
        with op.batch_alter_table('transactionpayer') as batch:
            batch.add_column(sa.Column('account_id', sa.Integer(), nullable=True))
            batch.create_foreign_key(
                'fk_transactionpayer_account', 'paymentaccount', ['account_id'], ['id']
            )
        op.create_index('ix_transactionpayer_account_id', 'transactionpayer', ['account_id'])

    # Backfill: pagador sem método próprio herda o método global da transação
    # (o campo por pagador existia mas nunca teve UI — estava todo NULL)
    op.execute(
        'UPDATE transactionpayer SET payment_method = ('
        ' SELECT t.payment_method FROM "transaction" t'
        ' WHERE t.id = transactionpayer.transaction_id'
        ') WHERE payment_method IS NULL'
    )

    if 'transactionadjustment' not in existing_tables:
        op.create_table(
            'transactionadjustment',
            sa.Column('id', sa.Integer(), primary_key=True),
            sa.Column('transaction_id', sa.Integer(), sa.ForeignKey('transaction.id'), nullable=False, index=True),
            sa.Column('type', sa.Enum(*ADJUSTMENT_TYPES, name='adjustmenttype'), nullable=False, server_default='other'),
            sa.Column('description', sa.String(), nullable=True),
            sa.Column('amount', sa.Numeric(20, 2), nullable=False),
            sa.Column('created_at', sa.DateTime(), nullable=False),
            sa.Column('updated_at', sa.DateTime(), nullable=False),
        )


def downgrade() -> None:
    op.drop_table('transactionadjustment')
    op.drop_index('ix_transactionpayer_account_id', table_name='transactionpayer')
    with op.batch_alter_table('transactionpayer') as batch:
        batch.drop_column('account_id')
    op.drop_table('paymentaccount')
