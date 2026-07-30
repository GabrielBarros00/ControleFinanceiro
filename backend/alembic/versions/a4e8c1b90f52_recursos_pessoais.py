"""Cartão, conta, financiamento e renda deixam de morar num workspace (ADR 0021)

A Onda 2 tinha tentado o meio-termo: o recurso morava num workspace e uma tabela
de vínculo o estendia a outros. A auditoria externa mostrou que o meio-termo
vazava e não servia:

- `CardWorkspaceAccess.access='full'` nunca foi consultado por rota nenhuma
  (`card_full_access_here()` existia sem um único chamador), então TODO cartão
  compartilhado entregava limite, valor comprometido e a fatura inteira — com as
  compras privadas de outro workspace dentro — a quem tivesse acesso completo no
  destino;
- e mesmo assim o cartão não podia ser USADO ali, porque a criação de lançamento
  exigia `card.workspace_id == workspace_id` e respondia 400.

A decisão do dono fecha o assunto pela raiz: recurso financeiro é da PESSOA e a
acompanha em todo workspace de que ela participa; ninguém mais vê nem usa. Sem
`workspace_id`, não existe consulta escopada por workspace capaz de alcançá-lo —
a privacidade deixa de depender de todo endpoint lembrar de filtrar.

O compartilhamento volta um dia com a forma certa: co-propriedade entre PESSOAS
(o casal que divide tudo mas tem contas separadas), não vínculo com espaços de
colaboração. Ver `docs/estudo-recursos-compartilhados.md`.

**Backfill do dono.** `creditcard` e `paymentaccount` aceitavam `owner_user_id`
NULL, que significava "da casa". Essas linhas herdam o dono do workspace em que
moravam (o membro com papel `owner`; na falta dele, o membro mais antigo). Linha
em workspace sem membro nenhum não tem dono possível e é removida — só existe em
base de desenvolvimento com resíduo de teste.

Revision ID: a4e8c1b90f52
Revises: f3a7d21e08b4
Create Date: 2026-07-30
"""
from alembic import op
import sqlalchemy as sa

revision = 'a4e8c1b90f52'
down_revision = 'f3a7d21e08b4'
branch_labels = None
depends_on = None

# As cinco tabelas de vínculo recurso↔workspace da Onda 2.
_TABELAS_DE_VINCULO = (
    'cardworkspaceaccess',
    'paymentaccountworkspaceshare',
    'financingworkspaceshare',
    'incomeworkspaceshare',
    'recurringincomeworkspaceshare',
)

# Dono do workspace: o membro com papel `owner`; senão o de menor user_id (o mais
# antigo, já que o id é sequencial). Subquery correlacionada, para valer por linha.
_DONO_DO_WORKSPACE = """
    COALESCE(
        (SELECT m.user_id FROM workspacemembership m
          WHERE m.workspace_id = {tabela}.workspace_id AND m.role = 'owner'
          ORDER BY m.user_id LIMIT 1),
        (SELECT m.user_id FROM workspacemembership m
          WHERE m.workspace_id = {tabela}.workspace_id
          ORDER BY m.user_id LIMIT 1)
    )
"""


def _colunas(bind, tabela: str) -> set:
    inspector = sa.inspect(bind)
    if tabela not in inspector.get_table_names():
        return set()
    return {c['name'] for c in inspector.get_columns(tabela)}


def _indices(bind, tabela: str) -> set:
    return {i['name'] for i in sa.inspect(bind).get_indexes(tabela)}


def _uniques(bind, tabela: str) -> set:
    return {u['name'] for u in sa.inspect(bind).get_unique_constraints(tabela)}


# `batch_alter_table` acumula as operações e só as executa no `flush()` da saída
# do contexto — envolver um `batch.drop_*` em try/except NÃO captura nada, porque
# a exceção nasce depois do bloco. Por isso a existência é conferida ANTES.


def upgrade() -> None:
    bind = op.get_bind()
    existentes = set(sa.inspect(bind).get_table_names())

    # --- 1. Dono obrigatório em cartão e conta -------------------------------
    # Ordem importa: backfill ANTES do NOT NULL, e o NOT NULL antes de largar o
    # workspace_id — que é justamente de onde o dono é derivado.
    for tabela in ('creditcard', 'paymentaccount'):
        if tabela not in existentes:
            continue
        colunas = _colunas(bind, tabela)
        if 'owner_user_id' not in colunas:
            op.add_column(tabela, sa.Column('owner_user_id', sa.Integer(), nullable=True))
        if 'workspace_id' in colunas:
            op.execute(sa.text(
                f"UPDATE {tabela} SET owner_user_id = "
                + _DONO_DO_WORKSPACE.format(tabela=tabela)
                + " WHERE owner_user_id IS NULL"
            ))
        # Sem dono possível (workspace sem membro): a linha não tem como existir
        # no modelo novo. Só ocorre com resíduo de teste.
        op.execute(sa.text(f"DELETE FROM {tabela} WHERE owner_user_id IS NULL"))

    # A fatura pertence ao cartão; sem cartão ela é órfã, e órfã de fatura foi
    # bug real da 3ª rodada de auditoria.
    if 'cardstatement' in existentes:
        op.execute(sa.text(
            "DELETE FROM cardstatement WHERE card_id NOT IN (SELECT id FROM creditcard)"
        ))
    if 'statementpayment' in existentes:
        op.execute(sa.text(
            "DELETE FROM statementpayment "
            "WHERE statement_id NOT IN (SELECT id FROM cardstatement)"
        ))

    # Lançamento que apontava para cartão/conta que sumiu perde a referência, em
    # vez de quebrar a FK.
    if 'transaction' in existentes:
        op.execute(sa.text(
            "UPDATE \"transaction\" SET credit_card_id = NULL "
            "WHERE credit_card_id IS NOT NULL "
            "AND credit_card_id NOT IN (SELECT id FROM creditcard)"
        ))
        op.execute(sa.text(
            "UPDATE \"transaction\" SET statement_id = NULL "
            "WHERE statement_id IS NOT NULL "
            "AND statement_id NOT IN (SELECT id FROM cardstatement)"
        ))
    if 'transactionpayer' in existentes:
        op.execute(sa.text(
            "UPDATE transactionpayer SET account_id = NULL "
            "WHERE account_id IS NOT NULL "
            "AND account_id NOT IN (SELECT id FROM paymentaccount)"
        ))

    # --- 2. Financiamento: autoria vira propriedade --------------------------
    if 'financing' in existentes:
        colunas = _colunas(bind, 'financing')
        if 'owner_user_id' not in colunas and 'created_by_user_id' in colunas:
            with op.batch_alter_table('financing') as batch:
                batch.alter_column(
                    'created_by_user_id',
                    new_column_name='owner_user_id',
                    existing_type=sa.Integer(),
                    existing_nullable=False,
                )

    # --- 3. Largar o workspace_id de todo recurso pessoal --------------------
    for tabela in ('creditcard', 'paymentaccount', 'financing', 'income', 'recurringincome',
                   'statementpayment'):
        if tabela not in existentes or 'workspace_id' not in _colunas(bind, tabela):
            continue
        # O índice de workspace_id cai junto com a coluna no Postgres, mas no
        # SQLite o batch recria a tabela e um índice remanescente na definição
        # velha faria a recriação falhar.
        indice = f'ix_{tabela}_workspace_id'
        tem_indice = indice in _indices(bind, tabela)
        with op.batch_alter_table(tabela) as batch:
            if tem_indice:
                batch.drop_index(indice)
            batch.drop_column('workspace_id')

    # `created_by_user_id` da renda recorrente era autoria duplicada: `user_id` já
    # diz de quem é a renda, e os dois sempre foram a mesma pessoa.
    if 'recurringincome' in existentes and 'created_by_user_id' in _colunas(bind, 'recurringincome'):
        with op.batch_alter_table('recurringincome') as batch:
            batch.drop_column('created_by_user_id')

    # --- 4. NOT NULL + índice no dono ---------------------------------------
    for tabela in ('creditcard', 'paymentaccount', 'financing'):
        if tabela not in existentes:
            continue
        with op.batch_alter_table(tabela) as batch:
            batch.alter_column(
                'owner_user_id', existing_type=sa.Integer(), nullable=False
            )
        indices = {i['name'] for i in sa.inspect(bind).get_indexes(tabela)}
        if f'ix_{tabela}_owner_user_id' not in indices:
            op.create_index(f'ix_{tabela}_owner_user_id', tabela, ['owner_user_id'])

    # --- 5. Conta: nome único POR DONO, não por workspace --------------------
    # Duas pessoas podem ter uma conta "Nubank"; a mesma pessoa, não.
    if 'paymentaccount' in existentes:
        op.execute(sa.text("""
            DELETE FROM paymentaccount WHERE id IN (
                SELECT id FROM (
                    SELECT id, ROW_NUMBER() OVER (
                        PARTITION BY owner_user_id, name ORDER BY id
                    ) AS n FROM paymentaccount
                ) dup WHERE dup.n > 1
            )
        """))
        antiga = 'uq_paymentaccount_workspace_name'
        tem_antiga = antiga in _uniques(bind, 'paymentaccount')
        with op.batch_alter_table('paymentaccount') as batch:
            if tem_antiga:
                batch.drop_constraint(antiga, type_='unique')
            batch.create_unique_constraint(
                'uq_paymentaccount_owner_name', ['owner_user_id', 'name']
            )

    # --- 6. As tabelas de vínculo somem -------------------------------------
    for tabela in _TABELAS_DE_VINCULO:
        if tabela in existentes:
            op.drop_table(tabela)


def downgrade() -> None:
    """Volta o `workspace_id`, mas NÃO o compartilhamento.

    Recriar as tabelas de vínculo vazias seria honesto quanto ao schema e mentiroso
    quanto ao dado: quem compartilhava o quê não sobrevive à ida. O recurso volta
    ancorado no primeiro workspace do dono, que é a única reconstrução possível.
    """
    bind = op.get_bind()
    existentes = set(sa.inspect(bind).get_table_names())

    primeiro_workspace = """
        (SELECT m.workspace_id FROM workspacemembership m
          WHERE m.user_id = {tabela}.{dono} ORDER BY m.workspace_id LIMIT 1)
    """

    for tabela, dono in (
        ('creditcard', 'owner_user_id'),
        ('paymentaccount', 'owner_user_id'),
        ('financing', 'owner_user_id'),
    ):
        if tabela not in existentes:
            continue
        op.add_column(tabela, sa.Column('workspace_id', sa.Integer(), nullable=True))
        op.execute(sa.text(
            f"UPDATE {tabela} SET workspace_id = "
            + primeiro_workspace.format(tabela=tabela, dono=dono)
        ))
        op.execute(sa.text(f"DELETE FROM {tabela} WHERE workspace_id IS NULL"))
        with op.batch_alter_table(tabela) as batch:
            batch.alter_column('workspace_id', existing_type=sa.Integer(), nullable=False)
        op.create_index(f'ix_{tabela}_workspace_id', tabela, ['workspace_id'])

    for tabela in ('income', 'recurringincome'):
        if tabela in existentes:
            op.add_column(tabela, sa.Column('workspace_id', sa.Integer(), nullable=True))
            op.create_index(f'ix_{tabela}_workspace_id', tabela, ['workspace_id'])

    if 'recurringincome' in existentes:
        op.add_column(
            'recurringincome', sa.Column('created_by_user_id', sa.Integer(), nullable=True)
        )
        op.execute(sa.text("UPDATE recurringincome SET created_by_user_id = user_id"))

    if 'statementpayment' in existentes:
        op.add_column(
            'statementpayment', sa.Column('workspace_id', sa.Integer(), nullable=True)
        )

    if 'financing' in existentes:
        with op.batch_alter_table('financing') as batch:
            batch.alter_column(
                'owner_user_id',
                new_column_name='created_by_user_id',
                existing_type=sa.Integer(),
                existing_nullable=False,
            )

    if 'paymentaccount' in existentes:
        nova = 'uq_paymentaccount_owner_name'
        tem_nova = nova in {
            u['name'] for u in sa.inspect(bind).get_unique_constraints('paymentaccount')
        }
        with op.batch_alter_table('paymentaccount') as batch:
            if tem_nova:
                batch.drop_constraint(nova, type_='unique')
            batch.create_unique_constraint(
                'uq_paymentaccount_workspace_name', ['workspace_id', 'name']
            )
