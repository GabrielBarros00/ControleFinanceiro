"""Dono do cartão de crédito (ADR 0018)

`CreditCard` era a única entidade financeira sem NENHUMA coluna de usuário. Isso
tinha duas consequências: não havia como esconder de um membro o cartão com que
ele não tem nada a ver (nome do banco e limite são dados pessoais), e não havia
como impedir que qualquer `member` mudasse o limite e o ciclo do cartão alheio —
os endpoints de cartão eram os únicos sem trava de autoria.

Backfill conservador, em duas situações distintas:

- Workspace com **um único membro**: o cartão só pode ser dele. Recebe o dono.
- Workspace com **vários membros**: não há como adivinhar de quem é. Fica `NULL`
  = "cartão compartilhado legado", que segue visível e editável por todos, como
  sempre foi, até alguém assumir a propriedade pela tela. Downgrade silencioso
  aqui esconderia da pessoa o cartão que ela usa todo dia.

Cartão criado a partir de agora nasce com dono (`credit_cards.create_credit_card`).

Revision ID: c5a8e31f7d94
Revises: b9d2f47a1c83
Create Date: 2026-07-30
"""
from alembic import op
import sqlalchemy as sa

revision = 'c5a8e31f7d94'
down_revision = 'b9d2f47a1c83'
branch_labels = None
depends_on = None

_TABELA = 'creditcard'
_COLUNA = 'owner_user_id'
_FK = 'fk_creditcard_owner_user_id_user'
_INDICE = f'ix_{_TABELA}_{_COLUNA}'


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
        op.create_index(_INDICE, _TABELA, [_COLUNA])

        # Só workspace de UM membro: a subquery de contagem é o que garante que
        # não se atribui cartão de casa compartilhada a um membro arbitrário.
        op.execute(sa.text(f"""
            UPDATE {_TABELA} SET {_COLUNA} = (
                SELECT m.user_id FROM workspacemembership m
                WHERE m.workspace_id = {_TABELA}.workspace_id
            )
            WHERE (
                SELECT COUNT(*) FROM workspacemembership m2
                WHERE m2.workspace_id = {_TABELA}.workspace_id
            ) = 1
        """))

    # FK via batch (ALTER no Postgres, recreate no SQLite) — mesmo padrão da
    # a1f7c3e9d024/a3e7b2c94f18. Sem ela o `alembic check` reprova nos dois dialetos.
    inspector = sa.inspect(bind)
    if not _tem_fk(inspector):
        with op.batch_alter_table(_TABELA) as batch:
            batch.create_foreign_key(_FK, 'user', [_COLUNA], ['id'])


def downgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    if _TABELA not in set(inspector.get_table_names()):
        return

    if _COLUNA in _colunas(inspector):
        if _INDICE in _indices(inspector):
            op.drop_index(_INDICE, table_name=_TABELA)
        # O drop_column no batch leva a FK junto
        with op.batch_alter_table(_TABELA) as batch:
            batch.drop_column(_COLUNA)
