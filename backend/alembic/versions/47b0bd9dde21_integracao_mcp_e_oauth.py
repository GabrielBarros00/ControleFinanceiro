"""Integração com agentes de IA: servidor MCP + authorization server OAuth 2.1 (ADR 0035)

Três grupos de mudança, todos aditivos — nenhuma coluna existente muda de
significado:

1. **OAuth** (`oauthclient`, `oauthgrant`, `oauthauthorizationcode`,
   `oauthtoken`): o authorization server que emite os tokens do `/mcp`. Tokens e
   códigos só como SHA-256; o `client_id` de um cliente CIMD é a própria URL do
   documento, daí os 512 caracteres.
2. **MCP** (`mcptoolcall`, `mcpoperation`, `mcpconfirmation`): a trilha
   operacional das chamadas, as chaves de idempotência e os tokens de confirmação
   de ação em massa.
3. **Colunas novas**:
   - `auditlog.origin` — por onde a mudança entrou (`mcp:<cliente>`); nula para
     o que veio do próprio app, que é todo o histórico existente.
   - `user.public_id` — identificador público, opaco e estável da conta, que a
     tool de perfil devolve. Nasce anulável, é preenchido linha a linha com um
     valor aleatório e só então vira NOT NULL + único: um DEFAULT de banco daria o
     MESMO valor a todas as contas existentes e a unicidade abortaria a migração.

Idempotente por inspeção, como as demais: um banco que já recebeu parte disto
pelo `create_all` de um ambiente antigo não pode abortar o deploy no meio.

Revision ID: 47b0bd9dde21
Revises: f2b6d41a9c03
Create Date: 2026-09-22
"""
import secrets
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = '47b0bd9dde21'
down_revision: Union[str, Sequence[str], None] = 'f2b6d41a9c03'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def _tabelas() -> set[str]:
    return set(sa.inspect(op.get_bind()).get_table_names())


def _colunas(nome_da_tabela: str) -> set[str]:
    return {c["name"] for c in sa.inspect(op.get_bind()).get_columns(nome_da_tabela)}


def _indices(nome_da_tabela: str) -> set[str]:
    return {i["name"] for i in sa.inspect(op.get_bind()).get_indexes(nome_da_tabela)}


def upgrade() -> None:
    tabelas = _tabelas()

    # ---- 1. OAuth -------------------------------------------------------------
    if 'oauthclient' not in tabelas:
        op.create_table(
            'oauthclient',
            sa.Column('id', sa.Integer(), nullable=False),
            sa.Column('client_id', sa.String(length=512), nullable=False),
            sa.Column('kind', sa.String(length=8), nullable=False),
            sa.Column('client_name', sa.String(length=120), nullable=False),
            sa.Column('client_uri', sa.String(length=512), nullable=True),
            sa.Column('redirect_uris', sa.JSON(), nullable=False),
            sa.Column('grant_types', sa.JSON(), nullable=False),
            sa.Column(
                'token_endpoint_auth_method', sa.String(length=32),
                server_default='none', nullable=False,
            ),
            sa.Column('client_secret_hash', sa.String(length=64), nullable=True),
            sa.Column('application_type', sa.String(length=16), nullable=True),
            sa.Column('software_id', sa.String(length=120), nullable=True),
            sa.Column('software_version', sa.String(length=60), nullable=True),
            sa.Column('metadata_expires_at', sa.DateTime(), nullable=True),
            sa.Column('created_at', sa.DateTime(), nullable=False),
            sa.Column('updated_at', sa.DateTime(), nullable=False),
            sa.Column('last_used_at', sa.DateTime(), nullable=True),
            sa.Column('disabled_at', sa.DateTime(), nullable=True),
            sa.PrimaryKeyConstraint('id'),
        )
        op.create_index(op.f('ix_oauthclient_client_id'), 'oauthclient', ['client_id'], unique=True)

    if 'oauthgrant' not in tabelas:
        op.create_table(
            'oauthgrant',
            sa.Column('id', sa.Integer(), nullable=False),
            sa.Column('user_id', sa.Integer(), nullable=False),
            sa.Column('client_pk', sa.Integer(), nullable=False),
            sa.Column('client_name', sa.String(length=120), nullable=False),
            sa.Column('scopes', sa.String(length=512), nullable=False),
            sa.Column('resource', sa.String(length=512), nullable=False),
            sa.Column('created_at', sa.DateTime(), nullable=False),
            sa.Column('last_used_at', sa.DateTime(), nullable=True),
            sa.Column('revoked_at', sa.DateTime(), nullable=True),
            sa.Column('revoked_reason', sa.String(length=32), nullable=True),
            sa.ForeignKeyConstraint(['client_pk'], ['oauthclient.id']),
            sa.ForeignKeyConstraint(['user_id'], ['user.id']),
            sa.PrimaryKeyConstraint('id'),
        )
        op.create_index(op.f('ix_oauthgrant_client_pk'), 'oauthgrant', ['client_pk'], unique=False)
        op.create_index('ix_oauthgrant_user_ativa', 'oauthgrant', ['user_id', 'revoked_at'], unique=False)
        op.create_index(op.f('ix_oauthgrant_user_id'), 'oauthgrant', ['user_id'], unique=False)

    if 'oauthauthorizationcode' not in tabelas:
        op.create_table(
            'oauthauthorizationcode',
            sa.Column('id', sa.Integer(), nullable=False),
            sa.Column('code_hash', sa.String(length=64), nullable=False),
            sa.Column('client_pk', sa.Integer(), nullable=False),
            sa.Column('user_id', sa.Integer(), nullable=False),
            sa.Column('redirect_uri', sa.Text(), nullable=False),
            sa.Column('scopes', sa.String(length=512), nullable=False),
            sa.Column('resource', sa.String(length=512), nullable=False),
            sa.Column('code_challenge', sa.String(length=128), nullable=False),
            sa.Column('expires_at', sa.DateTime(), nullable=False),
            sa.Column('used_at', sa.DateTime(), nullable=True),
            sa.Column('grant_id', sa.Integer(), nullable=True),
            sa.Column('created_at', sa.DateTime(), nullable=False),
            sa.ForeignKeyConstraint(['client_pk'], ['oauthclient.id']),
            sa.ForeignKeyConstraint(['grant_id'], ['oauthgrant.id']),
            sa.ForeignKeyConstraint(['user_id'], ['user.id']),
            sa.PrimaryKeyConstraint('id'),
        )
        op.create_index(
            op.f('ix_oauthauthorizationcode_client_pk'), 'oauthauthorizationcode', ['client_pk'], unique=False
        )
        op.create_index(
            op.f('ix_oauthauthorizationcode_code_hash'), 'oauthauthorizationcode', ['code_hash'], unique=True
        )
        op.create_index(
            op.f('ix_oauthauthorizationcode_grant_id'), 'oauthauthorizationcode', ['grant_id'], unique=False
        )
        op.create_index(
            op.f('ix_oauthauthorizationcode_user_id'), 'oauthauthorizationcode', ['user_id'], unique=False
        )

    if 'oauthtoken' not in tabelas:
        op.create_table(
            'oauthtoken',
            sa.Column('id', sa.Integer(), nullable=False),
            sa.Column('grant_id', sa.Integer(), nullable=False),
            sa.Column('kind', sa.String(length=8), nullable=False),
            sa.Column('token_hash', sa.String(length=64), nullable=False),
            sa.Column('scopes', sa.String(length=512), nullable=False),
            sa.Column('expires_at', sa.DateTime(), nullable=False),
            sa.Column('rotated_at', sa.DateTime(), nullable=True),
            sa.Column('revoked_at', sa.DateTime(), nullable=True),
            sa.Column('created_at', sa.DateTime(), nullable=False),
            sa.ForeignKeyConstraint(['grant_id'], ['oauthgrant.id']),
            sa.PrimaryKeyConstraint('id'),
        )
        op.create_index(op.f('ix_oauthtoken_expires_at'), 'oauthtoken', ['expires_at'], unique=False)
        op.create_index(op.f('ix_oauthtoken_grant_id'), 'oauthtoken', ['grant_id'], unique=False)
        op.create_index(op.f('ix_oauthtoken_token_hash'), 'oauthtoken', ['token_hash'], unique=True)

    # ---- 2. MCP ---------------------------------------------------------------
    if 'mcpconfirmation' not in tabelas:
        op.create_table(
            'mcpconfirmation',
            sa.Column('id', sa.Integer(), nullable=False),
            sa.Column('token_hash', sa.String(length=64), nullable=False),
            sa.Column('user_id', sa.Integer(), nullable=False),
            sa.Column('grant_id', sa.Integer(), nullable=True),
            sa.Column('action', sa.String(length=24), nullable=False),
            sa.Column('target_ids', sa.JSON(), nullable=False),
            sa.Column('params', sa.JSON(), nullable=True),
            sa.Column('expires_at', sa.DateTime(), nullable=False),
            sa.Column('used_at', sa.DateTime(), nullable=True),
            sa.Column('result', sa.JSON(), nullable=True),
            sa.Column('created_at', sa.DateTime(), nullable=False),
            sa.ForeignKeyConstraint(['grant_id'], ['oauthgrant.id']),
            sa.ForeignKeyConstraint(['user_id'], ['user.id']),
            sa.PrimaryKeyConstraint('id'),
        )
        op.create_index(op.f('ix_mcpconfirmation_expires_at'), 'mcpconfirmation', ['expires_at'], unique=False)
        op.create_index(op.f('ix_mcpconfirmation_token_hash'), 'mcpconfirmation', ['token_hash'], unique=True)
        op.create_index(op.f('ix_mcpconfirmation_user_id'), 'mcpconfirmation', ['user_id'], unique=False)

    if 'mcpoperation' not in tabelas:
        op.create_table(
            'mcpoperation',
            sa.Column('id', sa.Integer(), nullable=False),
            sa.Column('user_id', sa.Integer(), nullable=False),
            sa.Column('tool', sa.String(length=64), nullable=False),
            sa.Column('idempotency_key', sa.String(length=128), nullable=False),
            sa.Column('request_hash', sa.String(length=64), nullable=False),
            sa.Column('grant_id', sa.Integer(), nullable=True),
            sa.Column('result_ref', sa.JSON(), nullable=True),
            sa.Column('created_at', sa.DateTime(), nullable=False),
            sa.Column('expires_at', sa.DateTime(), nullable=False),
            sa.ForeignKeyConstraint(['grant_id'], ['oauthgrant.id']),
            sa.ForeignKeyConstraint(['user_id'], ['user.id']),
            sa.PrimaryKeyConstraint('id'),
            sa.UniqueConstraint('user_id', 'tool', 'idempotency_key', name='uq_mcpoperation_user_tool_key'),
        )
        op.create_index(op.f('ix_mcpoperation_expires_at'), 'mcpoperation', ['expires_at'], unique=False)
        op.create_index(op.f('ix_mcpoperation_user_id'), 'mcpoperation', ['user_id'], unique=False)

    if 'mcptoolcall' not in tabelas:
        op.create_table(
            'mcptoolcall',
            sa.Column('id', sa.Integer(), nullable=False),
            sa.Column('created_at', sa.DateTime(), nullable=False),
            sa.Column('user_id', sa.Integer(), nullable=True),
            sa.Column('grant_id', sa.Integer(), nullable=True),
            sa.Column('client_name', sa.String(length=120), nullable=True),
            sa.Column('client_info', sa.String(length=120), nullable=True),
            sa.Column('tool', sa.String(length=64), nullable=False),
            sa.Column('op_type', sa.String(length=16), nullable=False),
            sa.Column('outcome', sa.String(length=16), nullable=False),
            sa.Column('error_code', sa.String(length=40), nullable=True),
            sa.Column('duration_ms', sa.Integer(), nullable=False),
            sa.Column('request_id', sa.String(length=64), nullable=True),
            sa.Column('space_id', sa.Integer(), nullable=True),
            sa.Column('entity_type', sa.String(length=32), nullable=True),
            sa.Column('entity_ids', sa.JSON(), nullable=True),
            sa.Column('replayed', sa.Boolean(), nullable=False),
            sa.ForeignKeyConstraint(['grant_id'], ['oauthgrant.id']),
            sa.ForeignKeyConstraint(['user_id'], ['user.id']),
            sa.PrimaryKeyConstraint('id'),
        )
        op.create_index(op.f('ix_mcptoolcall_created_at'), 'mcptoolcall', ['created_at'], unique=False)
        op.create_index(op.f('ix_mcptoolcall_grant_id'), 'mcptoolcall', ['grant_id'], unique=False)
        op.create_index(op.f('ix_mcptoolcall_tool'), 'mcptoolcall', ['tool'], unique=False)
        op.create_index('ix_mcptoolcall_user_criado', 'mcptoolcall', ['user_id', 'created_at'], unique=False)

    # ---- 3. Colunas novas -----------------------------------------------------
    if 'origin' not in _colunas('auditlog'):
        op.add_column('auditlog', sa.Column('origin', sa.String(length=80), nullable=True))

    if 'public_id' not in _colunas('user'):
        op.add_column('user', sa.Column('public_id', sa.String(length=32), nullable=True))

    # Backfill SEMPRE (não só quando a coluna acabou de nascer): uma conta sem
    # `public_id` não teria como aparecer no perfil do MCP. Valor por LINHA, do
    # Python — um DEFAULT de banco daria o mesmo valor a todas as contas.
    usuarios = sa.table('user', sa.column('id', sa.Integer), sa.column('public_id', sa.String))
    bind = op.get_bind()
    sem_id = bind.execute(sa.select(usuarios.c.id).where(usuarios.c.public_id.is_(None))).scalars().all()
    for user_id in sem_id:
        bind.execute(
            usuarios.update()
            .where(usuarios.c.id == user_id)
            .values(public_id=f"usr_{secrets.token_hex(12)}")
        )

    if 'ix_user_public_id' not in _indices('user'):
        # Em lote: o SQLite não altera nulidade de coluna sem recriar a tabela.
        with op.batch_alter_table('user') as lote:
            lote.alter_column('public_id', existing_type=sa.String(length=32), nullable=False)
        op.create_index(op.f('ix_user_public_id'), 'user', ['public_id'], unique=True)


def downgrade() -> None:
    op.drop_index(op.f('ix_user_public_id'), table_name='user')
    with op.batch_alter_table('user') as lote:
        lote.drop_column('public_id')
    with op.batch_alter_table('auditlog') as lote:
        lote.drop_column('origin')
    op.drop_table('mcptoolcall')
    op.drop_table('mcpoperation')
    op.drop_table('mcpconfirmation')
    op.drop_table('oauthtoken')
    op.drop_table('oauthauthorizationcode')
    op.drop_table('oauthgrant')
    op.drop_table('oauthclient')
