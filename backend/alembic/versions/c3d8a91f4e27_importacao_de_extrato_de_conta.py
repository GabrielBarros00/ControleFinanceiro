"""Importação de extrato de CONTA: entradas, transferências e pagamento de fatura (ADR 0037)

A importação do ADR 0008 é de despesas de UM espaço: o valor vira módulo e toda
linha vira lançamento. Um extrato de conta tem entradas (salário, Pix recebido),
transferências entre contas da pessoa e o pagamento da fatura do cartão — que,
importados como despesa, inflavam o gasto e somavam duas vezes a fatura.

O lote de extrato é PESSOAL (a conta é da pessoa, ADR 0021), então
`workspace_id` passa a aceitar nulo no lote e na linha: só a linha classificada
como despesa leva o espaço em que ela foi lançada.

Colunas novas, todas anuláveis (os lotes antigos ficam como estão, `kind`
'expenses'):

- `importbatch.kind`, `importbatch.account_id`;
- `importrow.account_id`, `direction` ('in'/'out'), `classification`
  (expense/income/transfer/statement_payment), `external_id` (o id que o banco
  dá à linha, quando dá) e o que a linha criou: `income_id`, `transfer_id`,
  `statement_payment_id`.

Texto e não Enum do Postgres para `kind`, `direction` e `classification`: valor
novo num Enum exige `ALTER TYPE` à mão, e nem o SQLite nem o `alembic check` o
cobram. A validação fica no schema de entrada.

FKs por `batch_alter_table` (mesmo padrão de b6d4f28a9c15).

Revision ID: c3d8a91f4e27
Revises: 47b0bd9dde21
Create Date: 2026-09-24
"""
from alembic import op
import sqlalchemy as sa

revision = 'c3d8a91f4e27'
down_revision = '47b0bd9dde21'
branch_labels = None
depends_on = None

_FKS_DA_LINHA = (
    ('fk_importrow_account_id', 'account_id', 'paymentaccount'),
    ('fk_importrow_income_id', 'income_id', 'income'),
    ('fk_importrow_transfer_id', 'transfer_id', 'accounttransfer'),
    ('fk_importrow_statement_payment_id', 'statement_payment_id', 'statementpayment'),
)


def upgrade() -> None:
    op.add_column('importbatch', sa.Column('kind', sa.String(length=16), nullable=False, server_default='expenses'))
    op.add_column('importbatch', sa.Column('account_id', sa.Integer(), nullable=True))
    op.create_index('ix_importbatch_account_id', 'importbatch', ['account_id'])
    with op.batch_alter_table('importbatch') as lote:
        lote.alter_column('workspace_id', existing_type=sa.Integer(), nullable=True)
        lote.create_foreign_key('fk_importbatch_account_id', 'paymentaccount', ['account_id'], ['id'])

    op.add_column('importrow', sa.Column('account_id', sa.Integer(), nullable=True))
    op.add_column('importrow', sa.Column('direction', sa.String(length=3), nullable=True))
    op.add_column('importrow', sa.Column('classification', sa.String(length=20), nullable=True))
    op.add_column('importrow', sa.Column('external_id', sa.String(length=120), nullable=True))
    op.add_column('importrow', sa.Column('income_id', sa.Integer(), nullable=True))
    op.add_column('importrow', sa.Column('transfer_id', sa.Integer(), nullable=True))
    op.add_column('importrow', sa.Column('statement_payment_id', sa.Integer(), nullable=True))
    op.create_index('ix_importrow_account_id', 'importrow', ['account_id'])
    op.create_index('ix_importrow_external_id', 'importrow', ['external_id'])
    with op.batch_alter_table('importrow') as linha:
        linha.alter_column('workspace_id', existing_type=sa.Integer(), nullable=True)
        for nome, coluna, alvo in _FKS_DA_LINHA:
            linha.create_foreign_key(nome, alvo, [coluna], ['id'])


def downgrade() -> None:
    # Voltar exige que nenhuma linha sem espaço exista: lotes de extrato de conta
    # não têm como virar lote de espaço.
    op.execute("DELETE FROM importrow WHERE batch_id IN (SELECT id FROM importbatch WHERE kind <> 'expenses')")
    op.execute("DELETE FROM importbatch WHERE kind <> 'expenses'")
    with op.batch_alter_table('importrow') as linha:
        for nome, _coluna, _alvo in _FKS_DA_LINHA:
            linha.drop_constraint(nome, type_='foreignkey')
        linha.alter_column('workspace_id', existing_type=sa.Integer(), nullable=False)
    op.drop_index('ix_importrow_external_id', table_name='importrow')
    op.drop_index('ix_importrow_account_id', table_name='importrow')
    with op.batch_alter_table('importrow') as linha:
        for coluna in ('statement_payment_id', 'transfer_id', 'income_id', 'external_id', 'classification', 'direction', 'account_id'):
            linha.drop_column(coluna)
    with op.batch_alter_table('importbatch') as lote:
        lote.drop_constraint('fk_importbatch_account_id', type_='foreignkey')
        lote.alter_column('workspace_id', existing_type=sa.Integer(), nullable=False)
    op.drop_index('ix_importbatch_account_id', table_name='importbatch')
    with op.batch_alter_table('importbatch') as lote:
        lote.drop_column('account_id')
        lote.drop_column('kind')
