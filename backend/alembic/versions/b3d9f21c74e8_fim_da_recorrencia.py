"""A recorrência pode ter fim (ADR 0030)

Uma coluna em cada template, e nada retroativo.

A recorrência só tinha `start_date`. Uma mensalidade de faculdade paga por doze
anos virava uma série INFINITA: não havia "faltam 87 de 144", a previsão do mês
projetava o gasto para sempre, e o template continuava vivo e gerando muito
depois de a última parcela ter sido paga — até alguém lembrar de desativá-lo à
mão.

`end_date` é o teto que faltava, espelho exato do piso que já existia. Nasce
`NULL` em toda linha, que é "sem fim" — exatamente o comportamento de hoje —,
então nenhuma recorrência existente muda de forma nenhuma.

A renda ganha a mesma coluna pela mesma razão: bolsa e aluguel recebido por prazo
determinado também acabam.

**Sem `end_after_occurrences` no banco.** "Por 144 vezes" é a mesma informação
dita de outro jeito, e o servidor a converte em `end_date` na entrada. Guardar as
duas criaria duas verdades sobre quando a série acaba, e elas divergiriam na
primeira edição de frequência.

Revision ID: b3d9f21c74e8
Revises: a1c7e5b39d42
Create Date: 2026-08-19
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = 'b3d9f21c74e8'
down_revision: Union[str, Sequence[str], None] = 'a1c7e5b39d42'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

_TABELAS = ("recurringexpense", "recurringincome")


def _colunas(nome_da_tabela: str) -> set[str]:
    bind = op.get_bind()
    return {c["name"] for c in sa.inspect(bind).get_columns(nome_da_tabela)}


def upgrade() -> None:
    # Idempotente por inspeção, como as demais: um banco que já recebeu a coluna
    # por outro caminho (create_all de um ambiente antigo) não pode abortar o
    # deploy no meio.
    for tabela in _TABELAS:
        if 'end_date' not in _colunas(tabela):
            op.add_column(tabela, sa.Column('end_date', sa.Date(), nullable=True))


def downgrade() -> None:
    # `batch_alter_table` porque o SQLite não sabe soltar coluna sem recriar a
    # tabela — e o desenvolvimento roda em SQLite.
    for tabela in _TABELAS:
        if 'end_date' in _colunas(tabela):
            with op.batch_alter_table(tabela) as lote:
                lote.drop_column('end_date')
