"""Anexos: conteúdo fora do banco (ADR 0007)

O ADR 0007 decidiu que em produção o conteúdo vai para volume e o banco guarda
metadados + hash. Aqui vem o schema disso:

- `attachment.storage_key` (nullable, indexado): caminho relativo do objeto. O
  índice serve à exclusão — o armazenamento é endereçado por conteúdo e dedupica
  dentro do workspace, então antes de apagar o ARQUIVO é preciso saber se sobrou
  outra linha apontando para a mesma chave.
- `attachment.data` vira NULLABLE: passa a ser só o depósito LEGADO dos anexos
  que já existiam. `scripts/migrate_attachments_to_disk.py` move os bytes para o
  volume e zera a coluna; enquanto houver linha com `data`, a leitura cai nela.

A coluna `data` NÃO é dropada aqui de propósito. Dropar antes de o operador
rodar o script destruiria todo recibo já enviado — e migração que apaga dado do
usuário para "limpar schema" não se desfaz. A remoção é um passo separado,
depois que a contagem de pendentes zerar (o script reporta).

Revision ID: e3f9a17c4b28
Revises: d2c8f5b1e047
Create Date: 2026-07-29
"""
from alembic import op
import sqlalchemy as sa

revision = 'e3f9a17c4b28'
down_revision = 'd2c8f5b1e047'
branch_labels = None
depends_on = None

_INDICE = 'ix_attachment_storage_key'


def _colunas(bind):
    return {c['name']: c for c in sa.inspect(bind).get_columns('attachment')}


def upgrade() -> None:
    bind = op.get_bind()
    colunas = _colunas(bind)

    if 'storage_key' not in colunas:
        op.add_column('attachment', sa.Column('storage_key', sa.String(length=128), nullable=True))
        op.create_index(_INDICE, 'attachment', ['storage_key'])

    # `data` nullable: no SQLite o batch recria a tabela; no Postgres é ALTER.
    if colunas.get('data') is not None and not colunas['data']['nullable']:
        with op.batch_alter_table('attachment') as batch:
            batch.alter_column('data', existing_type=sa.LargeBinary(), nullable=True)


def downgrade() -> None:
    bind = op.get_bind()
    colunas = _colunas(bind)

    # Volta a NOT NULL só se não houver linha já migrada (data nula), senão a
    # constraint falharia — e o downgrade não pode inventar bytes de volta.
    pendentes = bind.execute(
        sa.text("SELECT COUNT(*) FROM attachment WHERE data IS NULL")
    ).scalar_one()
    if colunas.get('data') is not None and colunas['data']['nullable'] and not pendentes:
        with op.batch_alter_table('attachment') as batch:
            batch.alter_column('data', existing_type=sa.LargeBinary(), nullable=False)

    if 'storage_key' in colunas:
        op.drop_index(_INDICE, table_name='attachment')
        op.drop_column('attachment', 'storage_key')
