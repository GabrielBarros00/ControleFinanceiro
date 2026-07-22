"""Rendas recorrentes e acerto por mês

- settlement.billing_month: acerto vinculado a um mês (quita a "Dívidas do mês")
- recurringincome: template de renda recorrente
- income.recurring_income_id / income.billing_month: materialização + dedup

Revision ID: c2f7a91d4e63
Revises: b8e3f105c7a9
Create Date: 2026-07-22
"""
from alembic import op
import sqlalchemy as sa

revision = 'c2f7a91d4e63'
down_revision = 'b8e3f105c7a9'
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Idempotente (ADR 0005): DDL do SQLite não é transacional
    inspector = sa.inspect(op.get_bind())
    existing_tables = set(inspector.get_table_names())

    # Settlement.billing_month — acerto que quita a dívida de um mês específico
    settlement_cols = {c['name'] for c in inspector.get_columns('settlement')}
    if 'billing_month' not in settlement_cols:
        op.add_column('settlement', sa.Column('billing_month', sa.String(), nullable=True))
        op.create_index('ix_settlement_billing_month', 'settlement', ['billing_month'])

    # RecurringIncome — template de renda recorrente
    if 'recurringincome' not in existing_tables:
        op.create_table(
            'recurringincome',
            sa.Column('id', sa.Integer(), primary_key=True),
            sa.Column('workspace_id', sa.Integer(), sa.ForeignKey('workspace.id'), nullable=False),
            sa.Column('created_by_user_id', sa.Integer(), sa.ForeignKey('user.id'), nullable=True),
            sa.Column('user_id', sa.Integer(), sa.ForeignKey('user.id'), nullable=False),
            sa.Column('title', sa.String(), nullable=False),
            sa.Column('description', sa.String(), nullable=True),
            sa.Column('base_amount', sa.Numeric(precision=20, scale=2), nullable=False),
            sa.Column('currency', sa.String(), nullable=False, server_default='BRL'),
            sa.Column('category', sa.String(), nullable=True),
            sa.Column('frequency', sa.String(), nullable=False, server_default='monthly'),
            sa.Column('day_of_month', sa.Integer(), nullable=False, server_default='1'),
            sa.Column('day_of_week', sa.Integer(), nullable=True),
            sa.Column('month_of_year', sa.Integer(), nullable=True),
            sa.Column('is_active', sa.Boolean(), nullable=False, server_default=sa.true()),
            sa.Column('created_at', sa.DateTime(), nullable=False),
            sa.Column('updated_at', sa.DateTime(), nullable=False),
        )
        op.create_index('ix_recurringincome_workspace_id', 'recurringincome', ['workspace_id'])
        op.create_index('ix_recurringincome_user_id', 'recurringincome', ['user_id'])
        op.create_index('ix_recurringincome_title', 'recurringincome', ['title'])
        op.create_index('ix_recurringincome_category', 'recurringincome', ['category'])

    # Income.recurring_income_id + billing_month — origem recorrente e mês de competência
    income_cols = {c['name'] for c in inspector.get_columns('income')}
    if 'recurring_income_id' not in income_cols:
        op.add_column('income', sa.Column('recurring_income_id', sa.Integer(), nullable=True))
        op.create_index('ix_income_recurring_income_id', 'income', ['recurring_income_id'])
    if 'billing_month' not in income_cols:
        op.add_column('income', sa.Column('billing_month', sa.String(), nullable=True))
        op.create_index('ix_income_billing_month', 'income', ['billing_month'])


def downgrade() -> None:
    op.drop_index('ix_income_billing_month', table_name='income')
    op.drop_column('income', 'billing_month')
    op.drop_index('ix_income_recurring_income_id', table_name='income')
    op.drop_column('income', 'recurring_income_id')
    op.drop_table('recurringincome')
    op.drop_index('ix_settlement_billing_month', table_name='settlement')
    op.drop_column('settlement', 'billing_month')
