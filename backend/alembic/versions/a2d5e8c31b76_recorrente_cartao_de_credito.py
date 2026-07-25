"""Despesa recorrente vinculada a um cartão de crédito

- recurringexpense.credit_card_id: o snapshot (ADR 0012) já levava
  payment_method, mas sem o cartão a instância materializada nunca era roteada
  para uma fatura — assinatura no cartão ficava fora do statement.

Revision ID: a2d5e8c31b76
Revises: a1f7c3e9d024
Create Date: 2026-07-24
"""
from alembic import op
import sqlalchemy as sa

revision = 'a2d5e8c31b76'
down_revision = 'a1f7c3e9d024'
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Idempotente (ADR 0005): DDL do SQLite não é transacional
    inspector = sa.inspect(op.get_bind())
    if 'recurringexpense' not in inspector.get_table_names():
        return
    cols = {c['name'] for c in inspector.get_columns('recurringexpense')}
    if 'credit_card_id' in cols:
        return
    # FK nomeada: o SQLite exige batch_alter_table para criar a constraint
    with op.batch_alter_table('recurringexpense') as batch:
        batch.add_column(sa.Column('credit_card_id', sa.Integer(), nullable=True))
        batch.create_foreign_key(
            'fk_recurringexpense_credit_card_id', 'creditcard', ['credit_card_id'], ['id']
        )


def downgrade() -> None:
    with op.batch_alter_table('recurringexpense') as batch:
        batch.drop_constraint('fk_recurringexpense_credit_card_id', type_='foreignkey')
        batch.drop_column('credit_card_id')
