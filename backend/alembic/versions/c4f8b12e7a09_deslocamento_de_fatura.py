"""Deslocamento de fatura declarado (ADR 0032)

Uma coluna no lançamento e outra no template de recorrência. Nada retroativo.

A fatura de um cartão é composta pela data em que o EMISSOR processa a compra,
não pela data em que ela foi feita. Uma compra de 27/07 num cartão que fecha dia
28, capturada pelo estabelecimento só em 30/07, entra na fatura de agosto — e o
atraso é do estabelecimento (restaurante, hotel, companhia aérea capturam tarde;
mercado captura na hora), então nem o cartão nem o app têm como prevê-lo.

Antes disto a única alavanca sobre o destino da fatura era a `transaction_date`,
e mexer nela arrastava junto a competência (`billing_month`), a data da cotação
de câmbio numa compra estrangeira e a data exibida no extrato. Corrigir a fatura
exigia mentir sobre quando a compra aconteceu.

`statement_shift` nasce `0` em toda linha — "vale a regra do dia de fechamento",
que é exatamente o comportamento de hoje —, então nenhum lançamento existente
muda de fatura. É NOT NULL porque entra como operando de soma em todo caminho de
roteamento: com `NULL` cada um deles precisaria de um `or 0`, e a primeira
omissão viraria TypeError na criação de despesa.

**Relativo, não um mês absoluto.** Guardar "a fatura de setembro" não atenderia
nem a compra parcelada (o deslocamento vale para as N parcelas, cada uma no seu
ciclo) nem a recorrência (vale para ocorrências que ainda não têm mês), e
morreria na primeira edição de data.

Revision ID: c4f8b12e7a09
Revises: b3d9f21c74e8
Create Date: 2026-08-28
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = 'c4f8b12e7a09'
down_revision: Union[str, Sequence[str], None] = 'b3d9f21c74e8'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

_TABELAS = ("transaction", "recurringexpense")


def _colunas(nome_da_tabela: str) -> set[str]:
    bind = op.get_bind()
    return {c["name"] for c in sa.inspect(bind).get_columns(nome_da_tabela)}


def upgrade() -> None:
    # Idempotente por inspeção, como as demais migrações do projeto: um banco que
    # já recebeu a coluna por outro caminho (o `create_all` de um ambiente antigo)
    # não pode abortar o deploy no meio.
    #
    # `server_default="0"` e não só o default do Python: a coluna é NOT NULL e a
    # tabela `transaction` já tem linhas. Sem o default no BANCO, o `ALTER TABLE`
    # falha no Postgres — e no SQLite passaria, deixando as duas bases com
    # esquemas diferentes, que é o pior dos dois resultados.
    for tabela in _TABELAS:
        if 'statement_shift' not in _colunas(tabela):
            op.add_column(
                tabela,
                sa.Column(
                    'statement_shift',
                    sa.Integer(),
                    nullable=False,
                    server_default='0',
                ),
            )


def downgrade() -> None:
    # `batch_alter_table` porque o SQLite não sabe soltar coluna sem recriar a
    # tabela — e o desenvolvimento roda em SQLite.
    for tabela in _TABELAS:
        if 'statement_shift' in _colunas(tabela):
            with op.batch_alter_table(tabela) as lote:
                lote.drop_column('statement_shift')
