"""Saldo por conta, renda prevista e a conta de cada movimento (ADR 0034)

Três coisas que o app não sabia responder ganham lugar no esquema.

**1. A conta de cada movimento.** `PaymentAccount` existia desde o ADR 0004, mas só
duas FKs opcionais apontavam para ela e nenhum serviço de leitura as consultava — era
um rótulo. Para o saldo existir, todo movimento de caixa precisa poder dizer de qual
conta saiu ou em qual entrou: `income.account_id`, `amortizationinstallment.account_id`,
`settlement.from_account_id`/`to_account_id`, e `recurringexpense`/`recurringincome`
para que a ocorrência materializada nasça sabendo (é justamente o caso em que ninguém
vai abrir o lançamento para declarar).

**2. O que não tem origem em tabela nenhuma.** `accountentry` guarda a abertura ("em
01/09 eu tinha R$ 8.350,42") e o ajuste de conciliação; `accounttransfer` guarda o
dinheiro que muda de conta. Nada além disso: replicar aqui os movimentos que o
`CashFlowService` já deriva daria duas fontes para o mesmo fato.

A transferência é UMA linha com as duas pernas. Duas linhas ligadas por um id comum
dependeriam de a aplicação lembrar de escrever as duas; assim, perna órfã deixa de ser
representável.

**3. `income.settled_at` — e o `UPDATE` é o ponto desta migração.** Sem ele toda renda
existente ficaria com `settled_at NULL` e o `cash_in` de todos os meses fechados cairia
a zero na primeira leitura depois do deploy. É o mesmo backfill que a `a1c7e5b39d42`
fez do lado da despesa, com uma diferença deliberada: aqui ele para em HOJE. Renda com
data futura fica `NULL` — ela é prevista, e declarar recebido o que ainda não venceu
seria inventar caixa. Nenhum mês fechado muda; nenhum mês futuro é afirmado.

`recurringincome.auto_confirm` nasce **true**, ao contrário do `auto_settle` da despesa.
Renda recorrente é tipicamente salário e o comportamento atual já é "entrou": nascer
falso obrigaria todo mundo a confirmar à mão, todo mês, o que sempre contou sozinho.

**Nenhum saldo histórico é reconstruído.** Os dados existentes não permitem inferir
quanto havia em conta nenhuma — não há registro de quanto existia antes do primeiro
lançamento. Toda conta nasce sem abertura, e a tela pede o saldo atual + a data.

Os dois índices de coluna única sobre `account_id` são TROCADOS por parciais compostos:
quase toda linha tem `account_id` nulo, e o índice cheio era lido quase todo para nada
— o mesmo argumento do `ix_transaction_a_liquidar`.

Revision ID: d5a9e3c721b4
Revises: e7a4c9b18d52
Create Date: 2026-09-01
"""
from datetime import UTC, datetime
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = 'd5a9e3c721b4'
down_revision: Union[str, Sequence[str], None] = 'e7a4c9b18d52'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


#: Predicados dos índices parciais — os MESMOS dos `__table_args__` dos models.
#: Divergir aqui faria `alembic check` acusar drift a cada execução.
_ABERTURA = "kind = 'opening_balance' AND deleted_at IS NULL"
_VIVO = "deleted_at IS NULL"
_COM_CONTA = "account_id IS NOT NULL"
_COM_CONTA_VIVO = "account_id IS NOT NULL AND deleted_at IS NULL"
_COM_CONTA_PAGA = "account_id IS NOT NULL AND is_paid"

#: (tabela, coluna) das FKs novas para `paymentaccount`.
_COLUNAS_DE_CONTA = (
    ('income', 'account_id'),
    ('recurringexpense', 'account_id'),
    ('recurringincome', 'account_id'),
    ('amortizationinstallment', 'account_id'),
    ('settlement', 'from_account_id'),
    ('settlement', 'to_account_id'),
)


def _tabelas() -> set[str]:
    return set(sa.inspect(op.get_bind()).get_table_names())


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
    tabelas = _tabelas()

    # ---- 1. As duas tabelas novas -------------------------------------------
    if 'accountentry' not in tabelas:
        op.create_table(
            'accountentry',
            sa.Column('id', sa.Integer(), nullable=False),
            sa.Column('account_id', sa.Integer(), nullable=False),
            sa.Column(
                'kind',
                sa.Enum('opening_balance', 'adjustment', name='accountentrykind'),
                nullable=False,
            ),
            sa.Column('amount', sa.Numeric(precision=20, scale=2), nullable=False),
            sa.Column('occurred_at', sa.DateTime(), nullable=False),
            sa.Column('description', sa.String(), nullable=True),
            sa.Column('created_by_user_id', sa.Integer(), nullable=True),
            sa.Column('created_at', sa.DateTime(), nullable=False),
            sa.Column('updated_at', sa.DateTime(), nullable=False),
            sa.Column('deleted_at', sa.DateTime(), nullable=True),
            sa.ForeignKeyConstraint(['account_id'], ['paymentaccount.id']),
            sa.ForeignKeyConstraint(['created_by_user_id'], ['user.id']),
            sa.PrimaryKeyConstraint('id'),
        )
        op.create_index(
            op.f('ix_accountentry_account_id'), 'accountentry', ['account_id'], unique=False
        )
        # UMA abertura viva por conta: sem isto "a data do saldo inicial" não é bem
        # definida, e a regra que ignora os movimentos anteriores a ela fica sem
        # lado direito.
        op.create_index(
            'uq_accountentry_abertura',
            'accountentry',
            ['account_id'],
            unique=True,
            sqlite_where=sa.text(_ABERTURA),
            postgresql_where=sa.text(_ABERTURA),
        )
        op.create_index(
            'ix_accountentry_conta',
            'accountentry',
            ['account_id', 'occurred_at'],
            unique=False,
            sqlite_where=sa.text(_VIVO),
            postgresql_where=sa.text(_VIVO),
        )

    if 'accounttransfer' not in tabelas:
        op.create_table(
            'accounttransfer',
            sa.Column('id', sa.Integer(), nullable=False),
            sa.Column('from_account_id', sa.Integer(), nullable=False),
            sa.Column('to_account_id', sa.Integer(), nullable=False),
            sa.Column('from_amount', sa.Numeric(precision=20, scale=2), nullable=False),
            sa.Column('to_amount', sa.Numeric(precision=20, scale=2), nullable=False),
            sa.Column('exchange_rate', sa.Numeric(precision=20, scale=6), nullable=True),
            sa.Column('occurred_at', sa.DateTime(), nullable=False),
            sa.Column('note', sa.String(), nullable=True),
            sa.Column('created_by_user_id', sa.Integer(), nullable=True),
            sa.Column('created_at', sa.DateTime(), nullable=False),
            sa.Column('updated_at', sa.DateTime(), nullable=False),
            sa.Column('deleted_at', sa.DateTime(), nullable=True),
            sa.ForeignKeyConstraint(['from_account_id'], ['paymentaccount.id']),
            sa.ForeignKeyConstraint(['to_account_id'], ['paymentaccount.id']),
            sa.ForeignKeyConstraint(['created_by_user_id'], ['user.id']),
            sa.PrimaryKeyConstraint('id'),
            sa.CheckConstraint(
                'from_account_id != to_account_id',
                name='ck_accounttransfer_contas_distintas',
            ),
        )
        op.create_index(
            op.f('ix_accounttransfer_from_account_id'),
            'accounttransfer', ['from_account_id'], unique=False,
        )
        op.create_index(
            op.f('ix_accounttransfer_to_account_id'),
            'accounttransfer', ['to_account_id'], unique=False,
        )
        op.create_index(
            'ix_accounttransfer_origem',
            'accounttransfer',
            ['from_account_id', 'occurred_at'],
            unique=False,
            sqlite_where=sa.text(_VIVO),
            postgresql_where=sa.text(_VIVO),
        )
        op.create_index(
            'ix_accounttransfer_destino',
            'accounttransfer',
            ['to_account_id', 'occurred_at'],
            unique=False,
            sqlite_where=sa.text(_VIVO),
            postgresql_where=sa.text(_VIVO),
        )

    # ---- 2. A conta em cada movimento ---------------------------------------
    for tabela, coluna in _COLUNAS_DE_CONTA:
        if coluna not in _colunas(tabela):
            op.add_column(tabela, sa.Column(coluna, sa.Integer(), nullable=True))
            # FK nomeada e criada em lote: o SQLite não sabe acrescentar constraint
            # a uma tabela existente sem recriá-la.
            with op.batch_alter_table(tabela) as lote:
                lote.create_foreign_key(
                    f'fk_{tabela}_{coluna}_paymentaccount', 'paymentaccount',
                    [coluna], ['id'],
                )

    # ---- 3. Caixa e estado da renda ------------------------------------------
    if 'settled_at' not in _colunas('income'):
        op.add_column('income', sa.Column('settled_at', sa.DateTime(), nullable=True))
    if 'cancelled_at' not in _colunas('income'):
        op.add_column('income', sa.Column('cancelled_at', sa.DateTime(), nullable=True))

    # O backfill que preserva o passado. Roda SEMPRE (não só quando a coluna
    # acabou de nascer): um banco que ganhou a coluna pelo `create_all` a tem
    # vazia, e é exatamente esse o caso em que o histórico sumiria do caixa.
    #
    # `agora` vem do Python, e não de `CURRENT_TIMESTAMP`: em Postgres ele é
    # `timestamptz` e em SQLite é texto UTC, e o mesmo SQL compararia coisas
    # diferentes nos dois bancos. As colunas guardam UTC ingênuo.
    agora = datetime.now(UTC).replace(tzinfo=None)
    op.execute(
        sa.text(
            'UPDATE income SET settled_at = received_at '
            'WHERE settled_at IS NULL AND received_at <= :agora'
        ).bindparams(agora=agora)
    )

    if 'auto_confirm' not in _colunas('recurringincome'):
        op.add_column(
            'recurringincome',
            sa.Column(
                'auto_confirm', sa.Boolean(), nullable=False, server_default=sa.true()
            ),
        )

    if 'is_default' not in _colunas('paymentaccount'):
        op.add_column(
            'paymentaccount',
            sa.Column(
                'is_default', sa.Boolean(), nullable=False, server_default=sa.false()
            ),
        )

    # ---- 4. Índices do saldo: parciais no lugar dos cheios --------------------
    if 'ix_income_conta' not in _indices('income'):
        op.create_index(
            'ix_income_conta', 'income', ['account_id', 'received_at'], unique=False,
            sqlite_where=sa.text(_COM_CONTA_VIVO),
            postgresql_where=sa.text(_COM_CONTA_VIVO),
        )
    if 'ix_amortizationinstallment_conta' not in _indices('amortizationinstallment'):
        op.create_index(
            'ix_amortizationinstallment_conta', 'amortizationinstallment',
            ['account_id', 'paid_at'], unique=False,
            sqlite_where=sa.text(_COM_CONTA_PAGA),
            postgresql_where=sa.text(_COM_CONTA_PAGA),
        )
    if 'ix_transactionpayer_conta' not in _indices('transactionpayer'):
        op.create_index(
            'ix_transactionpayer_conta', 'transactionpayer',
            ['account_id', 'transaction_id'], unique=False,
            sqlite_where=sa.text(_COM_CONTA),
            postgresql_where=sa.text(_COM_CONTA),
        )
    if 'ix_statementpayment_conta' not in _indices('statementpayment'):
        op.create_index(
            'ix_statementpayment_conta', 'statementpayment',
            ['account_id', 'paid_at'], unique=False,
            sqlite_where=sa.text(_COM_CONTA_VIVO),
            postgresql_where=sa.text(_COM_CONTA_VIVO),
        )

    # Os cheios saem: o parcial acima cobre a mesma consulta lendo uma fração das
    # páginas. Manter os dois pagaria escrita em dobro para nada.
    if 'ix_transactionpayer_account_id' in _indices('transactionpayer'):
        op.drop_index('ix_transactionpayer_account_id', table_name='transactionpayer')
    if 'ix_statementpayment_account_id' in _indices('statementpayment'):
        op.drop_index('ix_statementpayment_account_id', table_name='statementpayment')


def downgrade() -> None:
    if 'ix_statementpayment_account_id' not in _indices('statementpayment'):
        op.create_index(
            'ix_statementpayment_account_id', 'statementpayment', ['account_id'],
            unique=False,
        )
    if 'ix_transactionpayer_account_id' not in _indices('transactionpayer'):
        op.create_index(
            'ix_transactionpayer_account_id', 'transactionpayer', ['account_id'],
            unique=False,
        )

    for tabela, indice in (
        ('statementpayment', 'ix_statementpayment_conta'),
        ('transactionpayer', 'ix_transactionpayer_conta'),
        ('amortizationinstallment', 'ix_amortizationinstallment_conta'),
        ('income', 'ix_income_conta'),
    ):
        if indice in _indices(tabela):
            op.drop_index(indice, table_name=tabela)

    # `batch_alter_table` porque o SQLite não sabe soltar coluna sem recriar a
    # tabela — e o desenvolvimento roda em SQLite.
    for tabela, coluna in (
        ('paymentaccount', 'is_default'),
        ('recurringincome', 'auto_confirm'),
        ('income', 'cancelled_at'),
        ('income', 'settled_at'),
    ) + tuple(reversed(_COLUNAS_DE_CONTA)):
        if coluna in _colunas(tabela):
            with op.batch_alter_table(tabela) as lote:
                lote.drop_column(coluna)

    tabelas = _tabelas()
    if 'accounttransfer' in tabelas:
        op.drop_table('accounttransfer')
    if 'accountentry' in tabelas:
        op.drop_table('accountentry')
    # O tipo nativo do Postgres não cai junto com a tabela.
    if op.get_bind().dialect.name == 'postgresql':
        op.execute(sa.text('DROP TYPE IF EXISTS accountentrykind'))
