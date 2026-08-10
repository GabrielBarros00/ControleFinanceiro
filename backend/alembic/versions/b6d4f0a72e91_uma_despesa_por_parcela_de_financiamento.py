"""Uma despesa VIVA por parcela de financiamento (Onda 8)

`Transaction.financing_installment_id` tinha índice comum, não único. Como
`pay_installment` checava `installment.is_paid` em Python e só depois inseria a
despesa, duas requisições simultâneas passavam as duas — a mesma parcela virava
DOIS lançamentos, dobrando o caixa do mês, os relatórios e o gasto do workspace.

A correção principal é a reivindicação atômica da parcela (`UPDATE ... WHERE
is_paid = false` em `api/routes/me_financing.py`). Este índice é a segunda linha
de defesa: qualquer caminho futuro que crie a despesa vinculada sem passar pela
reivindicação é recusado pelo BANCO, e não descoberto meses depois num relatório
que não fecha.

**O índice é PARCIAL, e `deleted_at IS NULL` não é otimização.**
`unpay_installment` estorna com SOFT delete e deixa o `financing_installment_id`
preenchido na linha morta. Um `UNIQUE` simples proibiria o fluxo legítimo pagar →
estornar → pagar de novo, trocando um bug de duplicação por um bug de bloqueio.

**Dedupe antes.** Um banco que já rodou a versão com a corrida pode ter
duplicatas, e o `CREATE UNIQUE INDEX` falharia no meio do `alembic upgrade head`
que o Dockerfile roda no start — o container não subiria. Sobrevivente: a despesa
VIVA de menor id (a primeira lançada); as demais são soft-deletadas, não
apagadas, porque podem ter pagador, divisão e anexo pendurados, e porque o
estorno de uma delas é um fato que aconteceu.

Revision ID: b6d4f0a72e91
Revises: a4e8c1b90f52
Create Date: 2026-08-09
"""
from alembic import op
import sqlalchemy as sa

revision = 'b6d4f0a72e91'
down_revision = 'a4e8c1b90f52'
branch_labels = None
depends_on = None

INDICE = 'uq_transaction_financing_installment'
PREDICADO = 'financing_installment_id IS NOT NULL AND deleted_at IS NULL'


def _dedupe(bind) -> None:
    """Soft-deleta despesas vivas excedentes por `financing_installment_id`.

    Mantém a de MENOR id — a primeira lançada é a que os relatórios do mês já
    contabilizaram; escolher a última moveria o histórico sem motivo.
    """
    bind.execute(sa.text("""
        UPDATE "transaction"
        SET deleted_at = CURRENT_TIMESTAMP
        WHERE financing_installment_id IS NOT NULL
          AND deleted_at IS NULL
          AND id NOT IN (
            SELECT keep_id FROM (
              SELECT MIN(id) AS keep_id
              FROM "transaction"
              WHERE financing_installment_id IS NOT NULL
                AND deleted_at IS NULL
              GROUP BY financing_installment_id
            ) sobreviventes
          )
    """))


def upgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    if 'transaction' not in set(inspector.get_table_names()):
        return
    if INDICE in {ix['name'] for ix in inspector.get_indexes('transaction')}:
        return

    _dedupe(bind)
    # `sqlite_where`/`postgresql_where`: o SQLAlchemy não tem `where` genérico
    # para índice parcial, e os dois motores estão em uso (SQLite em dev/CI,
    # Postgres em produção). Espelha o `__table_args__` de models/transaction.py
    # — divergir aqui é drift no `alembic check`.
    op.create_index(
        INDICE, 'transaction', ['financing_installment_id'], unique=True,
        sqlite_where=sa.text(PREDICADO),
        postgresql_where=sa.text(PREDICADO),
    )


def downgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    if 'transaction' not in set(inspector.get_table_names()):
        return
    if INDICE in {ix['name'] for ix in inspector.get_indexes('transaction')}:
        op.drop_index(INDICE, table_name='transaction')
