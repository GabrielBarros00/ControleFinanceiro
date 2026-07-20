"""Onda 3: ciclo da fatura (open→closed→paid) e pagamento por conta

- cardstatement.closed_at / paid_at: carimbos do ciclo (ADR 0011)
- statementpayment: registra a CONTA de onde saiu o pagamento da fatura
  (não é despesa — as compras já compõem o total; evita contagem dobrada)

Revision ID: d1f6b083a2c4
Revises: c7e4a95d63f1
Create Date: 2026-07-20
"""
from alembic import op
import sqlalchemy as sa

revision = 'd1f6b083a2c4'
down_revision = 'c7e4a95d63f1'
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Idempotente: DDL do SQLite não é transacional (ADR 0011/0005), o re-run
    # após falha parcial precisa completar em vez de quebrar
    inspector = sa.inspect(op.get_bind())
    existing_tables = set(inspector.get_table_names())

    statement_cols = {c['name'] for c in inspector.get_columns('cardstatement')}
    with op.batch_alter_table('cardstatement') as batch:
        if 'closed_at' not in statement_cols:
            batch.add_column(sa.Column('closed_at', sa.DateTime(), nullable=True))
        if 'paid_at' not in statement_cols:
            batch.add_column(sa.Column('paid_at', sa.DateTime(), nullable=True))

    if 'statementpayment' not in existing_tables:
        op.create_table(
            'statementpayment',
            sa.Column('id', sa.Integer(), primary_key=True),
            sa.Column('workspace_id', sa.Integer(), sa.ForeignKey('workspace.id'), nullable=False, index=True),
            sa.Column('statement_id', sa.Integer(), sa.ForeignKey('cardstatement.id'), nullable=False, index=True),
            sa.Column('account_id', sa.Integer(), sa.ForeignKey('paymentaccount.id'), nullable=True, index=True),
            sa.Column('amount', sa.Numeric(20, 2), nullable=False),
            sa.Column('paid_at', sa.DateTime(), nullable=False),
            sa.Column('note', sa.String(), nullable=True),
            sa.Column('created_by_user_id', sa.Integer(), sa.ForeignKey('user.id'), nullable=True),
            sa.Column('created_at', sa.DateTime(), nullable=False),
            sa.Column('updated_at', sa.DateTime(), nullable=False),
            sa.Column('deleted_at', sa.DateTime(), nullable=True),
        )


def downgrade() -> None:
    op.drop_table('statementpayment')
    with op.batch_alter_table('cardstatement') as batch:
        batch.drop_column('paid_at')
        batch.drop_column('closed_at')
