"""Completa o esquema: tabelas/colunas que só existiam via create_all em dev

A migração inicial (0df8b097a9e8) foi gerada sem vários models importados no
env.py. Esta revisão adiciona o que faltava para que `alembic upgrade head`
produza o esquema completo em produção.

Revision ID: c4e8f61a9b3d
Revises: f2a9c40d71aa
Create Date: 2026-07-11
"""
from alembic import op
import sqlalchemy as sa

revision = 'c4e8f61a9b3d'
down_revision = 'f2a9c40d71aa'
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Colunas ausentes em tabelas existentes
    op.add_column('user', sa.Column('needs_onboarding', sa.Boolean(), nullable=False, server_default=sa.true()))
    op.add_column('transaction', sa.Column('credit_card_id', sa.Integer(), nullable=True))
    op.add_column('transaction', sa.Column('statement_id', sa.Integer(), nullable=True))

    # Cartões de crédito
    op.create_table(
        'creditcard',
        sa.Column('id', sa.Integer(), primary_key=True),
        sa.Column('name', sa.String(), nullable=False),
        sa.Column('limit', sa.Numeric(precision=20, scale=2), nullable=False),
        sa.Column('closing_day', sa.Integer(), nullable=False),
        sa.Column('due_day', sa.Integer(), nullable=False),
        sa.Column('currency', sa.String(), nullable=False),
        sa.Column('workspace_id', sa.Integer(), sa.ForeignKey('workspace.id'), nullable=False),
        sa.Column('created_at', sa.DateTime(), nullable=False),
        sa.Column('updated_at', sa.DateTime(), nullable=False),
        sa.Column('deleted_at', sa.DateTime(), nullable=True),
    )
    op.create_index('ix_creditcard_name', 'creditcard', ['name'])
    op.create_index('ix_creditcard_workspace_id', 'creditcard', ['workspace_id'])

    op.create_table(
        'cardstatement',
        sa.Column('id', sa.Integer(), primary_key=True),
        sa.Column('month', sa.String(), nullable=False),
        sa.Column('closing_date', sa.DateTime(), nullable=False),
        sa.Column('due_date', sa.DateTime(), nullable=False),
        sa.Column('status', sa.Enum('open', 'closed', 'paid', 'overdue', name='statementstatus'), nullable=False),
        sa.Column('total_amount', sa.Numeric(precision=20, scale=2), nullable=False),
        sa.Column('card_id', sa.Integer(), sa.ForeignKey('creditcard.id'), nullable=False),
        sa.Column('created_at', sa.DateTime(), nullable=False),
        sa.Column('updated_at', sa.DateTime(), nullable=False),
    )
    op.create_index('ix_cardstatement_month', 'cardstatement', ['month'])
    op.create_index('ix_cardstatement_card_id', 'cardstatement', ['card_id'])

    # Itens de transação
    op.create_table(
        'transactionitem',
        sa.Column('id', sa.Integer(), primary_key=True),
        sa.Column('transaction_id', sa.Integer(), sa.ForeignKey('transaction.id'), nullable=False),
        sa.Column('title', sa.String(), nullable=False),
        sa.Column('description', sa.String(), nullable=True),
        sa.Column('amount', sa.Numeric(precision=20, scale=2), nullable=False),
        sa.Column('category_id', sa.Integer(), nullable=True),
        sa.Column('created_at', sa.DateTime(), nullable=False),
        sa.Column('updated_at', sa.DateTime(), nullable=False),
    )
    op.create_index('ix_transactionitem_transaction_id', 'transactionitem', ['transaction_id'])

    # Rendas
    op.create_table(
        'income',
        sa.Column('id', sa.Integer(), primary_key=True),
        sa.Column('title', sa.String(), nullable=False),
        sa.Column('description', sa.String(), nullable=True),
        sa.Column('amount', sa.Numeric(precision=20, scale=2), nullable=False),
        sa.Column('currency', sa.String(), nullable=False),
        sa.Column('received_at', sa.DateTime(), nullable=False),
        sa.Column('category', sa.String(), nullable=True),
        sa.Column('workspace_id', sa.Integer(), sa.ForeignKey('workspace.id'), nullable=False),
        sa.Column('user_id', sa.Integer(), sa.ForeignKey('user.id'), nullable=False),
        sa.Column('created_at', sa.DateTime(), nullable=False),
        sa.Column('updated_at', sa.DateTime(), nullable=False),
        sa.Column('deleted_at', sa.DateTime(), nullable=True),
    )
    op.create_index('ix_income_title', 'income', ['title'])
    op.create_index('ix_income_category', 'income', ['category'])
    op.create_index('ix_income_workspace_id', 'income', ['workspace_id'])
    op.create_index('ix_income_user_id', 'income', ['user_id'])

    # Estimativas mensais (orçamento)
    op.create_table(
        'monthlyestimate',
        sa.Column('id', sa.Integer(), primary_key=True),
        sa.Column('category', sa.String(), nullable=False),
        sa.Column('amount', sa.Numeric(precision=20, scale=2), nullable=False),
        sa.Column('month', sa.String(), nullable=False),
        sa.Column('description', sa.String(), nullable=True),
        sa.Column('workspace_id', sa.Integer(), sa.ForeignKey('workspace.id'), nullable=False),
        sa.Column('user_id', sa.Integer(), sa.ForeignKey('user.id'), nullable=False),
        sa.Column('created_at', sa.DateTime(), nullable=False),
        sa.Column('updated_at', sa.DateTime(), nullable=False),
        sa.Column('deleted_at', sa.DateTime(), nullable=True),
    )
    op.create_index('ix_monthlyestimate_category', 'monthlyestimate', ['category'])
    op.create_index('ix_monthlyestimate_month', 'monthlyestimate', ['month'])
    op.create_index('ix_monthlyestimate_workspace_id', 'monthlyestimate', ['workspace_id'])
    op.create_index('ix_monthlyestimate_user_id', 'monthlyestimate', ['user_id'])

    # Financiamentos
    op.create_table(
        'financing',
        sa.Column('id', sa.Integer(), primary_key=True),
        sa.Column('title', sa.String(), nullable=False),
        sa.Column('description', sa.String(), nullable=True),
        sa.Column('total_amount', sa.Numeric(precision=20, scale=2), nullable=False),
        sa.Column('interest_rate', sa.Numeric(precision=10, scale=6), nullable=False),
        sa.Column('start_date', sa.Date(), nullable=False),
        sa.Column('installments_count', sa.Integer(), nullable=False),
        sa.Column('method', sa.Enum('SAC', 'PRICE', name='amortizationmethod'), nullable=False),
        sa.Column('status', sa.Enum('active', 'settled', 'simulated', name='financingstatus'), nullable=False),
        sa.Column('currency', sa.String(), nullable=False),
        sa.Column('workspace_id', sa.Integer(), sa.ForeignKey('workspace.id'), nullable=False),
        sa.Column('created_by_user_id', sa.Integer(), sa.ForeignKey('user.id'), nullable=False),
        sa.Column('created_at', sa.DateTime(), nullable=False),
        sa.Column('updated_at', sa.DateTime(), nullable=False),
        sa.Column('deleted_at', sa.DateTime(), nullable=True),
    )
    op.create_index('ix_financing_title', 'financing', ['title'])
    op.create_index('ix_financing_workspace_id', 'financing', ['workspace_id'])

    op.create_table(
        'amortizationinstallment',
        sa.Column('id', sa.Integer(), primary_key=True),
        sa.Column('installment_number', sa.Integer(), nullable=False),
        sa.Column('due_date', sa.Date(), nullable=False),
        sa.Column('principal_amount', sa.Numeric(precision=20, scale=2), nullable=False),
        sa.Column('interest_amount', sa.Numeric(precision=20, scale=2), nullable=False),
        sa.Column('total_amount', sa.Numeric(precision=20, scale=2), nullable=False),
        sa.Column('remaining_balance', sa.Numeric(precision=20, scale=2), nullable=False),
        sa.Column('is_paid', sa.Boolean(), nullable=False),
        sa.Column('financing_id', sa.Integer(), sa.ForeignKey('financing.id'), nullable=False),
        sa.Column('paid_at', sa.DateTime(), nullable=True),
    )
    op.create_index('ix_amortizationinstallment_financing_id', 'amortizationinstallment', ['financing_id'])

    # FKs de transaction para cartão/fatura (batch para SQLite)
    with op.batch_alter_table('transaction') as batch_op:
        batch_op.create_index('ix_transaction_credit_card_id', ['credit_card_id'])
        batch_op.create_index('ix_transaction_statement_id', ['statement_id'])
        batch_op.create_foreign_key('fk_transaction_credit_card_id', 'creditcard', ['credit_card_id'], ['id'])
        batch_op.create_foreign_key('fk_transaction_statement_id', 'cardstatement', ['statement_id'], ['id'])


def downgrade() -> None:
    with op.batch_alter_table('transaction') as batch_op:
        batch_op.drop_constraint('fk_transaction_statement_id', type_='foreignkey')
        batch_op.drop_constraint('fk_transaction_credit_card_id', type_='foreignkey')
        batch_op.drop_index('ix_transaction_statement_id')
        batch_op.drop_index('ix_transaction_credit_card_id')

    op.drop_table('amortizationinstallment')
    op.drop_table('financing')
    op.drop_table('monthlyestimate')
    op.drop_table('income')
    op.drop_table('transactionitem')
    op.drop_table('cardstatement')
    op.drop_table('creditcard')

    op.drop_column('transaction', 'statement_id')
    op.drop_column('transaction', 'credit_card_id')
    op.drop_column('user', 'needs_onboarding')
