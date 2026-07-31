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

**Sentido único.** Não há `downgrade()`: o vínculo de compartilhamento e o
workspace de origem de cada recurso deixam de existir como dado aqui, e nenhuma
consulta os reconstitui. O rollback é restauração de backup — ver
`docs/runbook-deploy.md` e a mensagem em `_SEM_VOLTA`, no fim deste arquivo.

**Ordem das operações.** Toda referência é solta ANTES do `DELETE` que a
invalidaria. No Postgres a FK é verificada na hora, então "apaga agora, limpa
depois" não é uma limpeza atrasada: é a migração abortando — e, com o
`alembic upgrade head` que o Dockerfile roda no start, o container não sobe.

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


# Quem aponta para uma conta de pagamento. Ambas as pontas têm FK de verdade
# (`fk_transactionpayer_account` na c7e4a95d63f1; inline na d1f6b083a2c4), então
# nenhuma linha de `paymentaccount` pode ser apagada com uma delas apontando.
_REFERENCIAM_CONTA = ('transactionpayer', 'statementpayment')


def _funde_contas_duplicadas(bind, existentes: set) -> None:
    """Resolve o `(owner_user_id, name)` repetido ANTES de a unicidade nova valer.

    A mesma pessoa podia ter uma conta "Nubank" em cada workspace; com o
    `workspace_id` fora, as duas passam a colidir. A versão anterior resolvia com
    um `DELETE` do maior id — e isso tinha dois defeitos:

    1. `transactionpayer.account_id` e `statementpayment.account_id` continuavam
       apontando para a linha apagada. No SQLite virava referência órfã; no
       Postgres, onde a FK é verificada na hora, o `DELETE` **aborta a migração**
       — e o `alembic upgrade head` do Dockerfile roda no start do container, de
       modo que o backend não sobe.
    2. diferença de tipo, moeda ou estado era descartada em silêncio.

    Aqui: duplicata idêntica em `type` e `currency` é a MESMA conta vista de dois
    workspaces — as referências são reapontadas para a sobrevivente (a mais
    antiga) e só então a linha some. Qualquer diferença material é conta
    diferente com nome repetido: ela é **renomeada**, nunca apagada.
    """
    linhas = bind.execute(sa.text(
        "SELECT id, owner_user_id, name, type, currency FROM paymentaccount "
        "WHERE owner_user_id IS NOT NULL ORDER BY owner_user_id, name, id"
    )).mappings().all()

    grupos: dict = {}
    nomes_do_dono: dict = {}
    for linha in linhas:
        grupos.setdefault((linha['owner_user_id'], linha['name']), []).append(linha)
        nomes_do_dono.setdefault(linha['owner_user_id'], set()).add(linha['name'])

    referenciam = [t for t in _REFERENCIAM_CONTA if t in existentes]

    for (dono, nome), membros in grupos.items():
        if len(membros) < 2:
            continue
        # Menor id = a mais antiga; é ela que os relatórios já vinham somando.
        sobrevivente = membros[0]
        for dup in membros[1:]:
            mesma_conta = (
                dup['type'] == sobrevivente['type']
                and dup['currency'] == sobrevivente['currency']
            )
            if mesma_conta:
                for tabela in referenciam:
                    bind.execute(
                        sa.text(
                            f"UPDATE {tabela} SET account_id = :novo WHERE account_id = :velho"
                        ),
                        {"novo": sobrevivente['id'], "velho": dup['id']},
                    )
                bind.execute(
                    sa.text("DELETE FROM paymentaccount WHERE id = :id"), {"id": dup['id']}
                )
                continue

            # Nome livre para o dono: `(2)`, `(3)`… O sufixo é conferido contra os
            # nomes que ele já tem, senão o próprio desempate colidiria com uma
            # conta chamada "Nubank (2)" cadastrada à mão.
            usados = nomes_do_dono[dono]
            sufixo = 2
            while f"{nome} ({sufixo})" in usados:
                sufixo += 1
            novo_nome = f"{nome} ({sufixo})"
            usados.add(novo_nome)
            bind.execute(
                sa.text("UPDATE paymentaccount SET name = :nome WHERE id = :id"),
                {"nome": novo_nome, "id": dup['id']},
            )


def _solta_referencias_e_apaga_sem_dono(bind, existentes: set) -> None:
    """Apaga cartão/conta que não têm dono possível — soltando o que aponta para
    eles ANTES, não depois.

    Linha em workspace sem membro nenhum não tem de quem herdar o dono e não cabe
    no modelo novo (só existe em base de desenvolvimento com resíduo de teste).
    Mas ela é alvo de FK por três lados no caso do cartão (`transaction`,
    `cardstatement`, `recurringexpense`) e por dois no caso da conta. A versão
    anterior apagava primeiro e limpava depois: no Postgres a limpeza nunca era
    alcançada, porque o `DELETE` já tinha estourado.
    """
    if 'paymentaccount' in existentes:
        sem_dono = "SELECT id FROM paymentaccount WHERE owner_user_id IS NULL"
        for tabela in _REFERENCIAM_CONTA:
            if tabela in existentes and 'account_id' in _colunas(bind, tabela):
                op.execute(sa.text(
                    f"UPDATE {tabela} SET account_id = NULL "
                    f"WHERE account_id IN ({sem_dono})"
                ))
        op.execute(sa.text("DELETE FROM paymentaccount WHERE owner_user_id IS NULL"))

    if 'creditcard' in existentes:
        sem_dono = "SELECT id FROM creditcard WHERE owner_user_id IS NULL"
        faturas = f"SELECT id FROM cardstatement WHERE card_id IN ({sem_dono})"
        if 'transaction' in existentes:
            op.execute(sa.text(
                f'UPDATE "transaction" SET statement_id = NULL '
                f"WHERE statement_id IN ({faturas})"
            ))
            op.execute(sa.text(
                f'UPDATE "transaction" SET credit_card_id = NULL '
                f"WHERE credit_card_id IN ({sem_dono})"
            ))
        if 'recurringexpense' in existentes:
            op.execute(sa.text(
                f"UPDATE recurringexpense SET credit_card_id = NULL "
                f"WHERE credit_card_id IN ({sem_dono})"
            ))
        if 'statementpayment' in existentes:
            op.execute(sa.text(
                f"DELETE FROM statementpayment WHERE statement_id IN ({faturas})"
            ))
        if 'cardstatement' in existentes:
            op.execute(sa.text(f"DELETE FROM cardstatement WHERE card_id IN ({sem_dono})"))
        op.execute(sa.text("DELETE FROM creditcard WHERE owner_user_id IS NULL"))


def _varre_orfas_preexistentes(bind, existentes: set) -> None:
    """Rede de segurança para o que JÁ estava pendurado.

    O SQLite roda com `PRAGMA foreign_keys=OFF` por padrão, então uma base de
    desenvolvimento pode chegar aqui com referência quebrada de antes — e ela
    faria o `NOT NULL`/recriação de tabela mais adiante falhar. Idempotente: em
    base íntegra não toca em nada.
    """
    if 'cardstatement' in existentes:
        op.execute(sa.text(
            "DELETE FROM cardstatement WHERE card_id NOT IN (SELECT id FROM creditcard)"
        ))
    if 'statementpayment' in existentes:
        op.execute(sa.text(
            "DELETE FROM statementpayment "
            "WHERE statement_id NOT IN (SELECT id FROM cardstatement)"
        ))
        op.execute(sa.text(
            "UPDATE statementpayment SET account_id = NULL "
            "WHERE account_id IS NOT NULL "
            "AND account_id NOT IN (SELECT id FROM paymentaccount)"
        ))
    if 'transaction' in existentes:
        op.execute(sa.text(
            'UPDATE "transaction" SET credit_card_id = NULL '
            "WHERE credit_card_id IS NOT NULL "
            "AND credit_card_id NOT IN (SELECT id FROM creditcard)"
        ))
        op.execute(sa.text(
            'UPDATE "transaction" SET statement_id = NULL '
            "WHERE statement_id IS NOT NULL "
            "AND statement_id NOT IN (SELECT id FROM cardstatement)"
        ))
    if 'recurringexpense' in existentes:
        op.execute(sa.text(
            "UPDATE recurringexpense SET credit_card_id = NULL "
            "WHERE credit_card_id IS NOT NULL "
            "AND credit_card_id NOT IN (SELECT id FROM creditcard)"
        ))
    if 'transactionpayer' in existentes:
        op.execute(sa.text(
            "UPDATE transactionpayer SET account_id = NULL "
            "WHERE account_id IS NOT NULL "
            "AND account_id NOT IN (SELECT id FROM paymentaccount)"
        ))


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

    # --- 2. Conta duplicada do mesmo dono: funde ou renomeia -----------------
    # Antes da limpeza abaixo, porque a fusão REAPONTA referências em vez de as
    # deixar para trás — e antes da constraint nova, que é quem exige o desempate.
    if 'paymentaccount' in existentes:
        _funde_contas_duplicadas(bind, existentes)

    # --- 3. Sem dono possível: solta as referências e só então apaga ---------
    _solta_referencias_e_apaga_sem_dono(bind, existentes)

    # --- 3b. Órfãs que já vinham quebradas de antes --------------------------
    _varre_orfas_preexistentes(bind, existentes)

    # --- 4. Financiamento: autoria vira propriedade --------------------------
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

    # --- 5. Largar o workspace_id de todo recurso pessoal --------------------
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

    # --- 6. NOT NULL + índice no dono ---------------------------------------
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

    # --- 7. Conta: nome único POR DONO, não por workspace --------------------
    # Duas pessoas podem ter uma conta "Nubank"; a mesma pessoa, não. O desempate
    # aconteceu no passo 2 — aqui só a constraint muda de eixo.
    if 'paymentaccount' in existentes:
        antiga = 'uq_paymentaccount_workspace_name'
        tem_antiga = antiga in _uniques(bind, 'paymentaccount')
        with op.batch_alter_table('paymentaccount') as batch:
            if tem_antiga:
                batch.drop_constraint(antiga, type_='unique')
            batch.create_unique_constraint(
                'uq_paymentaccount_owner_name', ['owner_user_id', 'name']
            )

    # --- 8. As tabelas de vínculo somem -------------------------------------
    for tabela in _TABELAS_DE_VINCULO:
        if tabela in existentes:
            op.drop_table(tabela)


_SEM_VOLTA = """\
Esta revisão não tem downgrade: volte por restauração de backup.

`a4e8c1b90f52` apaga as cinco tabelas de vínculo da Onda 2 (cardworkspaceaccess,
paymentaccountworkspaceshare, financingworkspaceshare, incomeworkspaceshare,
recurringincomeworkspaceshare) e o `workspace_id` de cartão, conta, financiamento,
renda e pagamento de fatura. Nada disso é reconstituível a partir do estado novo:
quem compartilhava o quê, e em qual workspace cada recurso morava, deixa de existir
como dado no instante do upgrade.

A versão anterior deste downgrade fingia que dava: recriava o `workspace_id`
ancorando o recurso no PRIMEIRO workspace do dono e não recriava tabela de vínculo
nenhuma. O Alembic marcava `f3a7d21e08b4` como aplicada e a revisão anterior não
tinha como funcionar — um rollback que reporta sucesso e entrega um banco quebrado
é pior que um rollback que não existe.

Para voltar: restaure o dump tirado ANTES do upgrade (ver docs/runbook-deploy.md).
"""


def downgrade() -> None:
    """Recusa explícita — ver `_SEM_VOLTA`."""
    raise RuntimeError(_SEM_VOLTA)
