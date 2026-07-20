"""RBAC por enum de papel + convites de workspace

Revision ID: f2a9c40d71aa
Revises: 0df8b097a9e8
Create Date: 2026-07-11
"""
from alembic import op
import sqlalchemy as sa

revision = 'f2a9c40d71aa'
down_revision = '0df8b097a9e8'
branch_labels = None
depends_on = None


def upgrade() -> None:
    # 1) Papel textual no membership (substitui as tabelas Role/Permission)
    op.add_column(
        'workspacemembership',
        sa.Column('role', sa.String(length=20), nullable=False, server_default='member'),
    )
    # Backfill: memberships que apontavam para a Role "Owner" viram owner
    op.execute(
        "UPDATE workspacemembership SET role='owner' "
        "WHERE role_id IN (SELECT id FROM role WHERE name='Owner')"
    )
    with op.batch_alter_table('workspacemembership') as batch_op:
        batch_op.drop_column('role_id')

    # 2) Tabelas de RBAC dinâmico nunca usadas para autorização
    op.drop_table('rolepermissionlink')
    op.drop_table('permission')
    op.drop_table('role')

    # 3) Convites (por email e por link)
    op.create_table(
        'workspaceinvite',
        sa.Column('id', sa.Integer(), primary_key=True),
        sa.Column('workspace_id', sa.Integer(), sa.ForeignKey('workspace.id'), nullable=False),
        sa.Column('email', sa.String(), nullable=True),
        sa.Column('role', sa.String(length=20), nullable=False, server_default='member'),
        sa.Column('token', sa.String(), nullable=False),
        sa.Column('invited_by_user_id', sa.Integer(), sa.ForeignKey('user.id'), nullable=True),
        sa.Column('status', sa.String(length=20), nullable=False, server_default='pending'),
        sa.Column('expires_at', sa.DateTime(), nullable=False),
        sa.Column('max_uses', sa.Integer(), nullable=True),
        sa.Column('uses', sa.Integer(), nullable=False, server_default='0'),
        sa.Column('created_at', sa.DateTime(), nullable=False),
    )
    op.create_index('ix_workspaceinvite_workspace_id', 'workspaceinvite', ['workspace_id'])
    op.create_index('ix_workspaceinvite_email', 'workspaceinvite', ['email'])
    op.create_index('ix_workspaceinvite_token', 'workspaceinvite', ['token'], unique=True)


def downgrade() -> None:
    op.drop_index('ix_workspaceinvite_token', table_name='workspaceinvite')
    op.drop_index('ix_workspaceinvite_email', table_name='workspaceinvite')
    op.drop_index('ix_workspaceinvite_workspace_id', table_name='workspaceinvite')
    op.drop_table('workspaceinvite')

    op.create_table(
        'role',
        sa.Column('id', sa.Integer(), primary_key=True),
        sa.Column('name', sa.String(), nullable=False),
        sa.Column('description', sa.String(), nullable=True),
        sa.Column('workspace_id', sa.Integer(), sa.ForeignKey('workspace.id'), nullable=True),
    )
    op.create_table(
        'permission',
        sa.Column('id', sa.Integer(), primary_key=True),
        sa.Column('name', sa.String(), nullable=False, unique=True),
        sa.Column('description', sa.String(), nullable=True),
    )
    op.create_table(
        'rolepermissionlink',
        sa.Column('role_id', sa.Integer(), sa.ForeignKey('role.id'), primary_key=True),
        sa.Column('permission_id', sa.Integer(), sa.ForeignKey('permission.id'), primary_key=True),
    )

    op.add_column(
        'workspacemembership',
        sa.Column('role_id', sa.Integer(), nullable=False, server_default='1'),
    )
    with op.batch_alter_table('workspacemembership') as batch_op:
        batch_op.drop_column('role')
