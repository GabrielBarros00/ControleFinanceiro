"""Notificações do usuário

Convidar alguém que JÁ tinha conta adicionava a pessoa ao workspace na hora, sem
consentimento: quem soubesse um e-mail dava a si mesmo acesso à plateia de
finanças alheias, e o convidado passava a ver as contas de outra família sem
saber. O convite passou a esperar aceite, e o aviso precisa chegar por dois
canais — e-mail e dentro do app.

A tabela é de escopo PESSOAL (user_id), não de workspace: o destinatário do
convite ainda não é membro, então a notificação não pode depender de permissão
nele. Por isso `workspace_id` aqui é solto, sem FK — igual ao auditlog.

Revision ID: a5e9c37f2b10
Revises: f4a8d21c93e7
Create Date: 2026-07-26
"""
from alembic import op
import sqlalchemy as sa

revision = 'a5e9c37f2b10'
down_revision = 'f4a8d21c93e7'
branch_labels = None
depends_on = None


def upgrade() -> None:
    inspector = sa.inspect(op.get_bind())
    if 'notification' in inspector.get_table_names():
        return

    op.create_table(
        'notification',
        sa.Column('id', sa.Integer(), primary_key=True),
        sa.Column('user_id', sa.Integer(), sa.ForeignKey('user.id'), nullable=False),
        sa.Column('type', sa.String(), nullable=False),
        sa.Column('title', sa.String(), nullable=False),
        sa.Column('body', sa.String(), nullable=True),
        sa.Column('workspace_id', sa.Integer(), nullable=True),
        sa.Column('workspace_name', sa.String(), nullable=True),
        sa.Column('invite_token', sa.String(), nullable=True),
        sa.Column('read_at', sa.DateTime(), nullable=True),
        sa.Column('created_at', sa.DateTime(), nullable=False),
    )
    op.create_index('ix_notification_user_id', 'notification', ['user_id'])
    op.create_index('ix_notification_workspace_id', 'notification', ['workspace_id'])
    op.create_index('ix_notification_invite_token', 'notification', ['invite_token'])
    op.create_index('ix_notification_created_at', 'notification', ['created_at'])
    # A consulta quente é "minhas notificações, mais recentes primeiro"
    op.create_index('ix_notification_user_created', 'notification', ['user_id', 'created_at'])


def downgrade() -> None:
    inspector = sa.inspect(op.get_bind())
    if 'notification' not in inspector.get_table_names():
        return
    op.drop_table('notification')
