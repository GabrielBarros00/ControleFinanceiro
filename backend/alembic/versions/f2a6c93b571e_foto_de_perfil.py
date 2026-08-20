"""Foto de perfil: a chave do objeto no volume, e o tipo para servi-lo

Duas colunas em `user`, nenhuma delas com os bytes.

**Por que a imagem não entra no banco.** Vale aqui a mesma decisão do ADR 0007 e
do ADR 0016 para os anexos: o dump do Postgres é o que se restaura numa
emergência, e ele não deve crescer com conteúdo binário que não é finança. Os
bytes vão para o volume `attachments_data`, no namespace `avatars/`, endereçados
pelo SHA-256 do conteúdo. `avatar_key` é o ponteiro.

**Por que `avatar_content_type` existe.** A chave é um hash — não tem extensão, e
não há de onde inferir o tipo na hora de responder. Servir a foto com o
`Content-Type` errado significa, no melhor caso, imagem quebrada; e como a rota
manda `X-Content-Type-Options: nosniff`, o navegador não conserta o palpite.

**Por que `avatar_key` é indexada.** Duas contas com a mesma imagem apontam para
o MESMO arquivo (endereçamento por conteúdo dedupica). Trocar a própria foto,
então, só pode apagar o objeto antigo depois de perguntar se sobrou alguém
apontando para ele — e essa pergunta é uma busca por `avatar_key`. Sem o índice,
ela vira varredura da tabela de usuários a cada troca de foto. Mesma razão pela
qual `attachment.storage_key` é indexada.

Nada é retroativo: toda conta existente fica com `NULL` nas duas, que é o estado
"sem foto" — a interface continua desenhando a inicial do nome, como sempre fez.
Contas do Google também nascem sem: a foto de lá é baixada no login seguinte, e
por isso não pode ser semeada aqui (a migração não tem rede, nem sessão, nem o
`picture` de ninguém).

Revision ID: f2a6c93b571e
Revises: 0d91147a2292
Create Date: 2026-08-18
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = 'f2a6c93b571e'
down_revision: Union[str, Sequence[str], None] = '0d91147a2292'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def _colunas(nome_da_tabela: str) -> set[str]:
    bind = op.get_bind()
    return {c["name"] for c in sa.inspect(bind).get_columns(nome_da_tabela)}


def _indices(nome_da_tabela: str) -> set[str]:
    bind = op.get_bind()
    return {i["name"] for i in sa.inspect(bind).get_indexes(nome_da_tabela)}


def upgrade() -> None:
    # Idempotente por inspeção, como as demais: um banco que já recebeu a coluna
    # por outro caminho (create_all de um ambiente antigo) não pode fazer o
    # deploy abortar no meio.
    existentes = _colunas('user')
    if 'avatar_key' not in existentes:
        op.add_column('user', sa.Column('avatar_key', sa.String(length=128), nullable=True))
    if 'avatar_content_type' not in existentes:
        op.add_column('user', sa.Column('avatar_content_type', sa.String(length=32), nullable=True))
    if 'ix_user_avatar_key' not in _indices('user'):
        op.create_index(op.f('ix_user_avatar_key'), 'user', ['avatar_key'], unique=False)


def downgrade() -> None:
    # `batch_alter_table` porque o SQLite não sabe soltar coluna sem recriar a
    # tabela — e o desenvolvimento roda em SQLite.
    if 'ix_user_avatar_key' in _indices('user'):
        op.drop_index(op.f('ix_user_avatar_key'), table_name='user')
    with op.batch_alter_table('user') as lote:
        existentes = _colunas('user')
        if 'avatar_content_type' in existentes:
            lote.drop_column('avatar_content_type')
        if 'avatar_key' in existentes:
            lote.drop_column('avatar_key')
