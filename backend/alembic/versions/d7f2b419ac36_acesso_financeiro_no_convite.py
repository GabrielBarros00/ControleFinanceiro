"""Convite carrega o acesso financeiro (ADR 0018)

Quem convida decide o que a pessoa vai VER, e a decisão precisa viajar NO convite:
resolvê-la no aceite deixaria a escolha com o convidado, e resolvê-la por default
do papel devolveria o problema que a coluna veio resolver.

`server_default 'involved_only'`: convite antigo, ainda pendente, passa a conceder
acesso restrito ao ser aceito. É o lado seguro — quem convidou há três dias não
combinou nada sobre visibilidade, e o admin pode abrir depois na tela de membros.

Revision ID: d7f2b419ac36
Revises: c5a8e31f7d94
Create Date: 2026-07-30
"""
from alembic import op
import sqlalchemy as sa

revision = 'd7f2b419ac36'
down_revision = 'c5a8e31f7d94'
branch_labels = None
depends_on = None

_TABELA = 'workspaceinvite'
_COLUNA = 'financial_access'


def _colunas(inspector) -> set:
    return {c['name'] for c in inspector.get_columns(_TABELA)}


def upgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    if _TABELA not in set(inspector.get_table_names()):
        return
    if _COLUNA not in _colunas(inspector):
        op.add_column(
            _TABELA,
            sa.Column(
                _COLUNA,
                sa.String(length=20),
                nullable=False,
                server_default='involved_only',
            ),
        )


def downgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    if _TABELA not in set(inspector.get_table_names()):
        return
    if _COLUNA in _colunas(inspector):
        with op.batch_alter_table(_TABELA) as batch:
            batch.drop_column(_COLUNA)
