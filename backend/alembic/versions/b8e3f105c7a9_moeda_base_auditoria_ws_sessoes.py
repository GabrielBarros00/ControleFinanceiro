"""Onda 5: moeda-base por workspace, auditoria por workspace, estimate FK e sessões

- workspace.base_currency (ADR 0006): moeda-base configurável
- auditlog.workspace_id (AUD-001): trilha consultável por workspace
- monthlyestimate.category_id (BUD-001): orçamento por categoria FK
- refreshsession (SEC-004): sessões de refresh persistidas/rotacionáveis

Revision ID: b8e3f105c7a9
Revises: a4c8e17b92d5
Create Date: 2026-07-20
"""
from alembic import op
import sqlalchemy as sa

revision = 'b8e3f105c7a9'
down_revision = 'a4c8e17b92d5'
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Idempotente (ADR 0005): DDL do SQLite não é transacional
    inspector = sa.inspect(op.get_bind())
    existing_tables = set(inspector.get_table_names())

    ws_cols = {c['name'] for c in inspector.get_columns('workspace')}
    if 'base_currency' not in ws_cols:
        op.add_column('workspace', sa.Column('base_currency', sa.String(length=3), nullable=False, server_default='BRL'))

    audit_cols = {c['name'] for c in inspector.get_columns('auditlog')}
    if 'workspace_id' not in audit_cols:
        op.add_column('auditlog', sa.Column('workspace_id', sa.Integer(), nullable=True))
        op.create_index('ix_auditlog_workspace_id', 'auditlog', ['workspace_id'])

    est_cols = {c['name'] for c in inspector.get_columns('monthlyestimate')}
    if 'category_id' not in est_cols:
        op.add_column('monthlyestimate', sa.Column('category_id', sa.Integer(), nullable=True))
        op.create_index('ix_monthlyestimate_category_id', 'monthlyestimate', ['category_id'])

    if 'refreshsession' not in existing_tables:
        op.create_table(
            'refreshsession',
            sa.Column('id', sa.Integer(), primary_key=True),
            sa.Column('user_id', sa.Integer(), sa.ForeignKey('user.id'), nullable=False, index=True),
            sa.Column('jti', sa.String(), nullable=False),
            sa.Column('family_id', sa.String(), nullable=False, index=True),
            sa.Column('expires_at', sa.DateTime(), nullable=False),
            sa.Column('revoked_at', sa.DateTime(), nullable=True),
            sa.Column('created_at', sa.DateTime(), nullable=False),
            sa.UniqueConstraint('jti', name='uq_refreshsession_jti'),
        )
        op.create_index('ix_refreshsession_jti', 'refreshsession', ['jti'], unique=True)


def downgrade() -> None:
    op.drop_table('refreshsession')
    op.drop_index('ix_monthlyestimate_category_id', table_name='monthlyestimate')
    op.drop_column('monthlyestimate', 'category_id')
    op.drop_index('ix_auditlog_workspace_id', table_name='auditlog')
    op.drop_column('auditlog', 'workspace_id')
    op.drop_column('workspace', 'base_currency')
