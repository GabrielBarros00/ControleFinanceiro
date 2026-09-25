"""Estabelecimento: vocabulário do espaço ligado a lançamentos e recorrências (ADR 0038)

- `merchant`: nome único por espaço (índice único, como categoria e tag),
  apelidos normalizados em JSON, categoria padrão opcional, exclusão lógica.
- `transaction.merchant_id` e `recurringexpense.merchant_id`: anuláveis — sem
  estabelecimento, o título segue valendo como sempre.

FKs por `batch_alter_table` (mesmo padrão de b6d4f28a9c15).

Revision ID: d7e4b2a9c518
Revises: c3d8a91f4e27
Create Date: 2026-09-24
"""
from alembic import op
import sqlalchemy as sa

revision = 'd7e4b2a9c518'
down_revision = 'c3d8a91f4e27'
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        'merchant',
        sa.Column('id', sa.Integer(), primary_key=True),
        sa.Column('workspace_id', sa.Integer(), sa.ForeignKey('workspace.id'), nullable=False),
        sa.Column('name', sa.String(length=120), nullable=False),
        sa.Column('aliases', sa.JSON(), nullable=False),
        sa.Column('default_category_id', sa.Integer(), sa.ForeignKey('category.id'), nullable=True),
        sa.Column('created_at', sa.DateTime(), nullable=False),
        sa.Column('updated_at', sa.DateTime(), nullable=False),
        sa.Column('deleted_at', sa.DateTime(), nullable=True),
    )
    op.create_index('ix_merchant_workspace_id', 'merchant', ['workspace_id'])
    op.create_index('uq_merchant_workspace_name', 'merchant', ['workspace_id', 'name'], unique=True)

    op.add_column('transaction', sa.Column('merchant_id', sa.Integer(), nullable=True))
    op.create_index('ix_transaction_merchant_id', 'transaction', ['merchant_id'])
    with op.batch_alter_table('transaction') as lote:
        lote.create_foreign_key('fk_transaction_merchant_id', 'merchant', ['merchant_id'], ['id'])

    op.add_column('recurringexpense', sa.Column('merchant_id', sa.Integer(), nullable=True))
    with op.batch_alter_table('recurringexpense') as lote:
        lote.create_foreign_key('fk_recurringexpense_merchant_id', 'merchant', ['merchant_id'], ['id'])


def downgrade() -> None:
    with op.batch_alter_table('recurringexpense') as lote:
        lote.drop_constraint('fk_recurringexpense_merchant_id', type_='foreignkey')
        lote.drop_column('merchant_id')
    with op.batch_alter_table('transaction') as lote:
        lote.drop_constraint('fk_transaction_merchant_id', type_='foreignkey')
    op.drop_index('ix_transaction_merchant_id', table_name='transaction')
    with op.batch_alter_table('transaction') as lote:
        lote.drop_column('merchant_id')
    op.drop_index('uq_merchant_workspace_name', table_name='merchant')
    op.drop_index('ix_merchant_workspace_id', table_name='merchant')
    op.drop_table('merchant')
