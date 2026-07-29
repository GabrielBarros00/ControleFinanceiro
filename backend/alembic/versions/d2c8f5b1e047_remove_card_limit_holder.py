"""Remove transaction.card_limit_holder_user_id (coluna morta)

A coluna existia desde o esquema inicial, aparecia no `TransactionRead` e nos
tipos gerados do frontend — e **nunca foi lida nem escrita** por nenhum caminho
do app (nem rota, nem serviço, nem tela). Coluna nula em toda linha e presente
no contrato público da API só convida a alguém implementar contra ela.

Drop via `batch_alter_table`: no Postgres vira ALTER direto; no SQLite recria a
tabela (necessário para colunas com FK). Idempotente pelo inspector.

Revision ID: d2c8f5b1e047
Revises: c1b7e0a4d386
Create Date: 2026-07-29
"""
from alembic import op
import sqlalchemy as sa

revision = 'd2c8f5b1e047'
down_revision = 'c1b7e0a4d386'
branch_labels = None
depends_on = None

_COLUNA = 'card_limit_holder_user_id'


def _tem_coluna(bind) -> bool:
    inspector = sa.inspect(bind)
    return _COLUNA in {c['name'] for c in inspector.get_columns('transaction')}


def upgrade() -> None:
    bind = op.get_bind()
    if not _tem_coluna(bind):
        return
    with op.batch_alter_table('transaction') as batch:
        batch.drop_column(_COLUNA)


def downgrade() -> None:
    bind = op.get_bind()
    if _tem_coluna(bind):
        return
    op.add_column('transaction', sa.Column(_COLUNA, sa.Integer(), nullable=True))
