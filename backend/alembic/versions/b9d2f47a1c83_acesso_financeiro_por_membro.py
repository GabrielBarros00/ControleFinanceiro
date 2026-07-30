"""Acesso financeiro por membro: papel separado de visibilidade (ADR 0018)

Até aqui o papel controlava a ESCRITA e não protegia a LEITURA: qualquer membro
— inclusive `viewer` — lia o salário dos outros, os lançamentos individuais de
quem não o envolveu, os anexos desses lançamentos, os cartões e os totais da
casa. Cada listagem filtrava `workspace_id + deleted_at` e mais nada.

`financial_access` separa "o que eu posso ver" de "o que eu posso fazer". O
`server_default` é o valor FECHADO (`involved_only`): linha nova — venha de
convite, registro, aceite de link ou import — nasce privada, e abrir é ato
explícito.

Backfill conforme decisão do dono: `owner` e `admin` ficam com acesso completo,
`member` e `viewer` passam a ver só o que os envolve. Não é preservação cega do
comportamento antigo — é a correção que o dono pediu, e é reversível na tela de
membros. Owner e admin, de todo modo, têm acesso completo pelo CARGO
(`access_policy.effective_access`), então o backfill deles só deixa o banco
coerente com o que o código já garante.

Os três índices existem para o predicado de envolvimento
(`access_policy.involvement_filter`), que agora entra em toda listagem de
lançamento: sem eles, cada página do extrato varreria `transactionpayer` e
`transactionsplit` inteiras. `transactionitemshare.user_id` já era indexado.

Revision ID: b9d2f47a1c83
Revises: a3e7b2c94f18
Create Date: 2026-07-30
"""
from alembic import op
import sqlalchemy as sa

revision = 'b9d2f47a1c83'
down_revision = 'a3e7b2c94f18'
branch_labels = None
depends_on = None

_TABELA = 'workspacemembership'
_COLUNA = 'financial_access'

# (tabela, coluna) → índice novo para o predicado de envolvimento
_INDICES = (
    ('transaction', 'created_by_user_id'),
    ('transactionpayer', 'user_id'),
    ('transactionsplit', 'user_id'),
)


def _colunas(inspector, tabela: str) -> set:
    return {c['name'] for c in inspector.get_columns(tabela)}


def _indices(inspector, tabela: str) -> set:
    return {ix['name'] for ix in inspector.get_indexes(tabela)}


def upgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    tabelas = set(inspector.get_table_names())

    if _TABELA in tabelas and _COLUNA not in _colunas(inspector, _TABELA):
        op.add_column(
            _TABELA,
            sa.Column(
                _COLUNA,
                sa.String(length=20),
                nullable=False,
                server_default='involved_only',
            ),
        )
        # Owner/admin: acesso completo. O IN em texto casa com a coluna `role`,
        # que é String(20) e não enum nativo (ver f2a9c40d71aa).
        op.execute(sa.text(
            f"UPDATE {_TABELA} SET {_COLUNA} = 'full_workspace' "
            "WHERE role IN ('owner', 'admin')"
        ))

    for tabela, coluna in _INDICES:
        if tabela not in tabelas:
            continue
        nome = f'ix_{tabela}_{coluna}'
        inspector = sa.inspect(bind)
        if nome not in _indices(inspector, tabela):
            op.create_index(nome, tabela, [coluna])


def downgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    tabelas = set(inspector.get_table_names())

    for tabela, coluna in _INDICES:
        if tabela not in tabelas:
            continue
        nome = f'ix_{tabela}_{coluna}'
        inspector = sa.inspect(bind)
        if nome in _indices(inspector, tabela):
            op.drop_index(nome, table_name=tabela)

    if _TABELA in tabelas and _COLUNA in _colunas(inspector, _TABELA):
        with op.batch_alter_table(_TABELA) as batch:
            batch.drop_column(_COLUNA)
