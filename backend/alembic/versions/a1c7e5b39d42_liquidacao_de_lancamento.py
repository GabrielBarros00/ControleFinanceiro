"""Liquidação: quando o dinheiro saiu de fato (ADR 0029)

Três colunas e um backfill que **não muda nenhum número do passado**.

`transaction.settled_at` é a data em que o dinheiro saiu. Antes ela não existia:
`CashFlowService` lia `transaction_date` e afirmava que toda despesa fora do
cartão saía do bolso no instante em que era registrada. O boleto que vence dia 10
virava saída de caixa no dia 10, pago ou não, e `payment_method` — `pix`, `cash`,
`boleto`, `bank_transfer` — não entrava em consulta nenhuma.

**O `UPDATE` é o ponto desta migração.** Sem ele, toda linha existente ficaria com
`settled_at NULL` e o caixa de todos os meses fechados cairia para zero na
primeira leitura depois do deploy — meses que já foram conferidos, exportados e
usados para acertar contas entre pessoas. Com ele, cada lançamento antigo é
liquidado na sua própria data e o histórico responde exatamente o mesmo de antes.
O `WHERE settled_at IS NULL` mantém a migração repetível: rodar duas vezes não
sobrescreve o que já foi liquidado de verdade.

`workspace.settlement_tracking` nasce **true** — o espaço existente passa a
controlar pagamento, e a promessa acima é o que torna isso seguro: o passado já
está liquidado, então só o que for lançado daqui pra frente cai na fila.

`recurringexpense.auto_settle` nasce **false**. É a coluna que diz "o banco debita
sozinho"; assumi-la verdadeira reintroduziria o defeito para toda recorrência já
cadastrada, que é justamente onde ele mais aparecia.

**Sem o índice, a tela de Contas a pagar varre a tabela inteira.** Ele é PARCIAL,
com o mesmo predicado do recorte (`ix_transaction_a_liquidar`): num app em que a
esmagadora maioria das linhas está liquidada, um índice cheio seria quase todo
lido para nada.

Revision ID: a1c7e5b39d42
Revises: f2a6c93b571e
Create Date: 2026-08-19
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = 'a1c7e5b39d42'
down_revision: Union[str, Sequence[str], None] = 'f2a6c93b571e'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


#: Predicado do índice parcial — o MESMO de `models/transaction.py::_A_LIQUIDAR`.
#: Divergir aqui faria `alembic check` acusar drift a cada execução.
_A_LIQUIDAR = "settled_at IS NULL AND deleted_at IS NULL AND credit_card_id IS NULL"


def _colunas(nome_da_tabela: str) -> set[str]:
    bind = op.get_bind()
    return {c["name"] for c in sa.inspect(bind).get_columns(nome_da_tabela)}


def _indices(nome_da_tabela: str) -> set[str]:
    bind = op.get_bind()
    return {i["name"] for i in sa.inspect(bind).get_indexes(nome_da_tabela)}


def upgrade() -> None:
    # Idempotente por inspeção, como as demais: um banco que já recebeu a coluna
    # por outro caminho (create_all de um ambiente antigo) não pode abortar o
    # deploy no meio.
    if 'settled_at' not in _colunas('transaction'):
        op.add_column('transaction', sa.Column('settled_at', sa.DateTime(), nullable=True))

    # O backfill que preserva o passado. Roda SEMPRE (não só quando a coluna
    # acabou de nascer): um banco que ganhou a coluna pelo `create_all` a tem
    # vazia, e é exatamente esse o caso em que o histórico sumiria do caixa.
    op.execute(
        sa.text(
            'UPDATE "transaction" SET settled_at = transaction_date '
            'WHERE settled_at IS NULL'
        )
    )

    if 'settlement_tracking' not in _colunas('workspace'):
        op.add_column(
            'workspace',
            sa.Column(
                'settlement_tracking',
                sa.Boolean(),
                nullable=False,
                server_default=sa.true(),
            ),
        )

    if 'auto_settle' not in _colunas('recurringexpense'):
        op.add_column(
            'recurringexpense',
            sa.Column(
                'auto_settle',
                sa.Boolean(),
                nullable=False,
                server_default=sa.false(),
            ),
        )

    if 'ix_transaction_a_liquidar' not in _indices('transaction'):
        op.create_index(
            'ix_transaction_a_liquidar',
            'transaction',
            ['workspace_id', 'billing_month'],
            unique=False,
            sqlite_where=sa.text(_A_LIQUIDAR),
            postgresql_where=sa.text(_A_LIQUIDAR),
        )


def downgrade() -> None:
    if 'ix_transaction_a_liquidar' in _indices('transaction'):
        op.drop_index('ix_transaction_a_liquidar', table_name='transaction')
    # `batch_alter_table` porque o SQLite não sabe soltar coluna sem recriar a
    # tabela — e o desenvolvimento roda em SQLite.
    if 'auto_settle' in _colunas('recurringexpense'):
        with op.batch_alter_table('recurringexpense') as lote:
            lote.drop_column('auto_settle')
    if 'settlement_tracking' in _colunas('workspace'):
        with op.batch_alter_table('workspace') as lote:
            lote.drop_column('settlement_tracking')
    if 'settled_at' in _colunas('transaction'):
        with op.batch_alter_table('transaction') as lote:
            lote.drop_column('settled_at')
