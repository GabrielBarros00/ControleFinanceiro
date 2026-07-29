"""Backfill de transaction.billing_month (mês único das agregações)

As agregações de despesa passaram a recortar por `billing_month` em vez de uma
janela sobre `transaction_date`. Os dois discordavam na virada do mês: o
`transaction_date` é um INSTANTE gravado em UTC, então uma despesa lançada às
22h do dia 31 em Brasília já está no dia 1 do mês seguinte — ela aparecia em
Lançamentos e nas Dívidas de julho e nos Relatórios de agosto, a mesma despesa
em dois meses diferentes na mesma sessão.

Todo caminho de criação preenche `billing_month` (formulário, bulk, import,
recorrência, parcelas, financiamento), mas a coluna é nullable e existe desde
antes disso. Uma linha com `billing_month IS NULL` sumiria de TODA agregação
depois da troca — daí este backfill, derivado do próprio `transaction_date`.

Idempotente por natureza: só toca linhas com a coluna nula.

Revision ID: f5b1c8e93d07
Revises: e3f9a17c4b28
Create Date: 2026-07-29
"""
from alembic import op
import sqlalchemy as sa

revision = 'f5b1c8e93d07'
down_revision = 'e3f9a17c4b28'
branch_labels = None
depends_on = None

# A formatação de data diverge entre os dialetos (strftime não existe no
# Postgres, to_char não existe no SQLite), então cada um tem a sua expressão.
_EXPR = {
    'postgresql': "to_char(transaction_date, 'YYYY-MM')",
    'sqlite': "strftime('%Y-%m', transaction_date)",
}


def upgrade() -> None:
    bind = op.get_bind()
    expr = _EXPR.get(bind.dialect.name)
    if expr is None:  # dialeto não previsto: não adivinha, apenas não faz nada
        return
    # `transaction` é palavra reservada (no SQLite quebra o parser, no Postgres
    # é `TRANSACTION` do controle de transação) — o identificador vai entre aspas.
    op.execute(sa.text(
        'UPDATE "transaction" '
        f"SET billing_month = {expr} "
        "WHERE billing_month IS NULL AND transaction_date IS NOT NULL"
    ))


def downgrade() -> None:
    # Backfill de dado derivado não tem volta útil: apagar os valores
    # reintroduziria exatamente o buraco que esta migração fecha.
    pass
