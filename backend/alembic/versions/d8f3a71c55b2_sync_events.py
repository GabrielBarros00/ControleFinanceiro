"""Eventos de sincronização (WebSocket): workspace.event_seq + tabela syncevent

Revision ID: d8f3a71c55b2
Revises: b7c1e94d02fe
Create Date: 2026-07-11
"""
from alembic import op
import sqlalchemy as sa

revision = 'd8f3a71c55b2'
down_revision = 'b7c1e94d02fe'
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        'workspace',
        sa.Column('event_seq', sa.Integer(), nullable=False, server_default='0'),
    )

    op.create_table(
        'syncevent',
        sa.Column('id', sa.Integer(), primary_key=True),
        sa.Column('workspace_id', sa.Integer(), sa.ForeignKey('workspace.id'), nullable=False),
        sa.Column('seq', sa.Integer(), nullable=False),
        sa.Column('event_type', sa.String(), nullable=False),
        sa.Column('resource_type', sa.String(), nullable=True),
        sa.Column('resource_id', sa.Integer(), nullable=True),
        sa.Column('actor_user_id', sa.Integer(), sa.ForeignKey('user.id'), nullable=True),
        sa.Column('created_at', sa.DateTime(), nullable=False),
        sa.UniqueConstraint('workspace_id', 'seq', name='uq_syncevent_workspace_seq'),
    )
    op.create_index('ix_syncevent_workspace_id', 'syncevent', ['workspace_id'])


def downgrade() -> None:
    op.drop_index('ix_syncevent_workspace_id', table_name='syncevent')
    op.drop_table('syncevent')
    op.drop_column('workspace', 'event_seq')
