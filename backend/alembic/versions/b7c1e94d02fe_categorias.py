"""Categorias por workspace + FK em transactionitem.category_id

Revision ID: b7c1e94d02fe
Revises: f2a9c40d71aa
Create Date: 2026-07-11
"""
from alembic import op
import sqlalchemy as sa

revision = 'b7c1e94d02fe'
down_revision = 'c4e8f61a9b3d'
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        'category',
        sa.Column('id', sa.Integer(), primary_key=True),
        sa.Column('workspace_id', sa.Integer(), sa.ForeignKey('workspace.id'), nullable=False),
        sa.Column('name', sa.String(), nullable=False),
        sa.Column('color', sa.String(), nullable=True),
        sa.Column('icon', sa.String(), nullable=True),
        sa.Column('created_at', sa.DateTime(), nullable=False),
        sa.Column('updated_at', sa.DateTime(), nullable=False),
        sa.Column('deleted_at', sa.DateTime(), nullable=True),
    )
    op.create_index('ix_category_workspace_id', 'category', ['workspace_id'])
    op.create_index('ix_category_name', 'category', ['name'])

    with op.batch_alter_table('transactionitem') as batch_op:
        batch_op.create_index('ix_transactionitem_category_id', ['category_id'])
        batch_op.create_foreign_key(
            'fk_transactionitem_category_id', 'category', ['category_id'], ['id']
        )


def downgrade() -> None:
    with op.batch_alter_table('transactionitem') as batch_op:
        batch_op.drop_constraint('fk_transactionitem_category_id', type_='foreignkey')
        batch_op.drop_index('ix_transactionitem_category_id')

    op.drop_index('ix_category_name', table_name='category')
    op.drop_index('ix_category_workspace_id', table_name='category')
    op.drop_table('category')
