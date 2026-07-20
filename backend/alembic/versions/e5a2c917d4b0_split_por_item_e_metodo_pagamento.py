"""Divisão por item (transactionitemshare) + método de pagamento na transação

Revision ID: e5a2c917d4b0
Revises: d8f3a71c55b2
Create Date: 2026-07-18
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision = 'e5a2c917d4b0'
down_revision = 'd8f3a71c55b2'
branch_labels = None
depends_on = None

SPLIT_MODE_VALUES = ('transaction', 'item')
PAYMENT_METHOD_VALUES = (
    'credit_card', 'debit_card', 'pix', 'cash', 'bank_transfer', 'boleto', 'other'
)
SPLIT_METHOD_VALUES = ('equal', 'percentage', 'fixed')


def _is_postgres() -> bool:
    return op.get_bind().dialect.name == 'postgresql'


# No Postgres os enums são tipos nativos: os novos são criados explicitamente
# (checkfirst) e TODAS as referências de coluna usam create_type=False para o
# add_column/create_table não tentar um segundo CREATE TYPE. No SQLite o
# sa.Enum vira VARCHAR + CHECK e nada disso se aplica.
def _split_mode_type():
    if _is_postgres():
        return postgresql.ENUM(*SPLIT_MODE_VALUES, name='splitmode', create_type=False)
    return sa.Enum(*SPLIT_MODE_VALUES, name='splitmode')


def _payment_method_type():
    if _is_postgres():
        return postgresql.ENUM(*PAYMENT_METHOD_VALUES, name='paymentmethod', create_type=False)
    return sa.Enum(*PAYMENT_METHOD_VALUES, name='paymentmethod')


def _split_method_type():
    # Tipo já existente desde o reinit v2 — nunca recriar
    if _is_postgres():
        return postgresql.ENUM(*SPLIT_METHOD_VALUES, name='splitmethod', create_type=False)
    return sa.Enum(*SPLIT_METHOD_VALUES, name='splitmethod')


def upgrade() -> None:
    bind = op.get_bind()
    if _is_postgres():
        postgresql.ENUM(*SPLIT_MODE_VALUES, name='splitmode').create(bind, checkfirst=True)
        postgresql.ENUM(*PAYMENT_METHOD_VALUES, name='paymentmethod').create(bind, checkfirst=True)

    op.add_column(
        'transaction',
        sa.Column('split_mode', _split_mode_type(), nullable=False, server_default='transaction'),
    )
    op.add_column(
        'transaction',
        sa.Column('payment_method', _payment_method_type(), nullable=True),
    )
    op.create_index('ix_transaction_payment_method', 'transaction', ['payment_method'])

    # Backfill: transação pendurada num cartão foi paga no crédito; as demais
    # ficam NULL ("não informado") e a UI mantém o fallback de exibição
    op.execute(
        'UPDATE "transaction" SET payment_method=\'credit_card\' '
        'WHERE credit_card_id IS NOT NULL AND deleted_at IS NULL'
    )

    op.add_column('transactionitem', sa.Column('position', sa.Integer(), nullable=False, server_default='0'))
    op.add_column('transactionitem', sa.Column('quantity', sa.Numeric(12, 3), nullable=False, server_default='1'))
    op.add_column('transactionitem', sa.Column('unit_amount', sa.Numeric(20, 2), nullable=True))

    op.create_table(
        'transactionitemshare',
        sa.Column('id', sa.Integer(), primary_key=True),
        sa.Column('item_id', sa.Integer(), sa.ForeignKey('transactionitem.id'), nullable=False),
        sa.Column('user_id', sa.Integer(), sa.ForeignKey('user.id'), nullable=False),
        sa.Column('split_method', _split_method_type(), nullable=False),
        sa.Column('input_value', sa.Numeric(20, 2), nullable=False),
        sa.Column('computed_amount', sa.Numeric(20, 2), nullable=False),
        sa.Column('created_at', sa.DateTime(), nullable=False),
        sa.Column('updated_at', sa.DateTime(), nullable=False),
        sa.UniqueConstraint('item_id', 'user_id', name='uq_itemshare_item_user'),
    )
    op.create_index('ix_transactionitemshare_item_id', 'transactionitemshare', ['item_id'])
    op.create_index('ix_transactionitemshare_user_id', 'transactionitemshare', ['user_id'])


def downgrade() -> None:
    op.drop_index('ix_transactionitemshare_user_id', table_name='transactionitemshare')
    op.drop_index('ix_transactionitemshare_item_id', table_name='transactionitemshare')
    op.drop_table('transactionitemshare')

    with op.batch_alter_table('transactionitem') as batch_op:
        batch_op.drop_column('unit_amount')
        batch_op.drop_column('quantity')
        batch_op.drop_column('position')

    op.drop_index('ix_transaction_payment_method', table_name='transaction')
    with op.batch_alter_table('transaction') as batch_op:
        batch_op.drop_column('payment_method')
        batch_op.drop_column('split_mode')

    if _is_postgres():
        bind = op.get_bind()
        postgresql.ENUM(name='paymentmethod').drop(bind, checkfirst=True)
        postgresql.ENUM(name='splitmode').drop(bind, checkfirst=True)
        # 'splitmethod' preexiste a esta migration — permanece
