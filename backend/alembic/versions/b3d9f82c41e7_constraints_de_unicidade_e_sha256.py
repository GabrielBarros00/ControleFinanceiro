"""Onda 1: unicidade de fatura/parcela e hash de anexo

- uq_statement_card_month: uma fatura por (cartão, mês) — a derivação
  server-side da fatura (ADR 0002) conta com esta garantia no banco.
- uq_amortization_financing_number: número de parcela único por financiamento.
- attachment.sha256: hash de integridade preenchido no upload (SEC-003).

Revision ID: b3d9f82c41e7
Revises: a9c4e72d18f3
Create Date: 2026-07-19
"""
from alembic import op
import sqlalchemy as sa

revision = 'b3d9f82c41e7'
down_revision = 'a9c4e72d18f3'
branch_labels = None
depends_on = None


def upgrade() -> None:
    # batch_alter_table: no SQLite constraints exigem rebuild da tabela;
    # no Postgres vira ALTER TABLE direto
    with op.batch_alter_table('cardstatement') as batch:
        batch.create_unique_constraint('uq_statement_card_month', ['card_id', 'month'])

    with op.batch_alter_table('amortizationinstallment') as batch:
        batch.create_unique_constraint(
            'uq_amortization_financing_number', ['financing_id', 'installment_number']
        )

    op.add_column('attachment', sa.Column('sha256', sa.String(length=64), nullable=True))


def downgrade() -> None:
    op.drop_column('attachment', 'sha256')
    with op.batch_alter_table('amortizationinstallment') as batch:
        batch.drop_constraint('uq_amortization_financing_number', type_='unique')
    with op.batch_alter_table('cardstatement') as batch:
        batch.drop_constraint('uq_statement_card_month', type_='unique')
