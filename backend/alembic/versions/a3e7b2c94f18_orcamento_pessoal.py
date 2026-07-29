"""Orçamento com escopo: meta da casa × meta pessoal de cada membro

O Início comparava a despesa PESSOAL do usuário (soma dos splits dele) com o
orçamento da CASA (soma de todos os `MonthlyEstimate` do workspace, sem filtro
por pessoa). Num workspace de duas pessoas com rateio igual a barra marcava
~50% quando a casa já tinha consumido 100% — e a tela de Relatórios, que
comparava casa com casa, mostrava outro número para o MESMO orçamento.

`owner_user_id` dá escopo à meta: `NULL` = casa, preenchido = pessoal daquele
membro. Não há backfill — todo orçamento existente é da casa, que é exatamente
o `NULL` que a coluna nova ganha.

O índice único passa a incluir o dono: a meta da casa e a meta pessoal de cada
membro convivem na mesma categoria e no mesmo mês. (NULLs seguem distintos na
unique, como já acontecia com `category_id` — a idempotência de verdade é da
rota, não do banco.)

Revision ID: a3e7b2c94f18
Revises: f5b1c8e93d07
Create Date: 2026-07-29
"""
from alembic import op
import sqlalchemy as sa

revision = 'a3e7b2c94f18'
down_revision = 'f5b1c8e93d07'
branch_labels = None
depends_on = None

_TABELA = 'monthlyestimate'
_COLUNA = 'owner_user_id'
_FK = 'fk_monthlyestimate_owner_user_id_user'
_INDICE_NOVO = 'uq_estimate_workspace_owner_category_month'
_INDICE_ANTIGO = 'uq_estimate_workspace_category_month'


def _colunas(inspector) -> set:
    return {c['name'] for c in inspector.get_columns(_TABELA)}


def _indices(inspector) -> set:
    return {ix['name'] for ix in inspector.get_indexes(_TABELA)}


def _tem_fk(inspector) -> bool:
    return any(
        _COLUNA in fk['constrained_columns']
        for fk in inspector.get_foreign_keys(_TABELA)
    )


def upgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    if _TABELA not in set(inspector.get_table_names()):
        return

    if _COLUNA not in _colunas(inspector):
        op.add_column(_TABELA, sa.Column(_COLUNA, sa.Integer(), nullable=True))
        op.create_index(f'ix_{_TABELA}_{_COLUNA}', _TABELA, [_COLUNA])

    # FK criada JUNTO, via batch (ALTER direto no Postgres, recreate no SQLite) —
    # o padrão que a `a1f7c3e9d024` estabeleceu ao fechar o drift das outras
    # quatro colunas. Adicionar a coluna sem a FK reabriria o mesmo buraco, e o
    # `alembic check` (gate de CI nos dois dialetos) reprovaria na hora.
    inspector = sa.inspect(bind)
    if not _tem_fk(inspector):
        with op.batch_alter_table(_TABELA) as batch:
            batch.create_foreign_key(_FK, 'user', [_COLUNA], ['id'])

    inspector = sa.inspect(bind)
    indices = _indices(inspector)
    if _INDICE_ANTIGO in indices:
        op.drop_index(_INDICE_ANTIGO, table_name=_TABELA)
    if _INDICE_NOVO not in indices:
        op.create_index(
            _INDICE_NOVO, _TABELA,
            ['workspace_id', _COLUNA, 'category_id', 'month'],
            unique=True,
        )


def downgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    if _TABELA not in set(inspector.get_table_names()):
        return

    indices = _indices(inspector)
    if _INDICE_NOVO in indices:
        op.drop_index(_INDICE_NOVO, table_name=_TABELA)
    if _INDICE_ANTIGO not in indices:
        # As metas pessoais precisam sair antes: sem o dono na chave elas
        # colidiriam com a meta da casa da mesma categoria/mês.
        op.execute(sa.text(
            f"DELETE FROM {_TABELA} WHERE {_COLUNA} IS NOT NULL"
        ))
        op.create_index(
            _INDICE_ANTIGO, _TABELA,
            ['workspace_id', 'category_id', 'month'],
            unique=True,
        )

    inspector = sa.inspect(bind)
    if _COLUNA in _colunas(inspector):
        if f'ix_{_TABELA}_{_COLUNA}' in _indices(inspector):
            op.drop_index(f'ix_{_TABELA}_{_COLUNA}', table_name=_TABELA)
        # O drop_column no batch já leva a FK junto (o SQLite recria a tabela;
        # no Postgres o ALTER derruba a constraint dependente).
        with op.batch_alter_table(_TABELA) as batch:
            batch.drop_column(_COLUNA)
