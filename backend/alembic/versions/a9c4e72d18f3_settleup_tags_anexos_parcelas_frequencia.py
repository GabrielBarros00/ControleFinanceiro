"""Backlog: settlements, tags, anexos, parcelamento e frequência de recorrência

Revision ID: a9c4e72d18f3
Revises: e5a2c917d4b0
Create Date: 2026-07-18
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision = 'a9c4e72d18f3'
down_revision = 'e5a2c917d4b0'
branch_labels = None
depends_on = None

FREQUENCY_VALUES = ('weekly', 'monthly', 'yearly')


def _is_postgres() -> bool:
    return op.get_bind().dialect.name == 'postgresql'


def _frequency_type():
    if _is_postgres():
        return postgresql.ENUM(*FREQUENCY_VALUES, name='recurrencefrequency', create_type=False)
    return sa.Enum(*FREQUENCY_VALUES, name='recurrencefrequency')


def upgrade() -> None:
    bind = op.get_bind()
    if _is_postgres():
        postgresql.ENUM(*FREQUENCY_VALUES, name='recurrencefrequency').create(bind, checkfirst=True)

    # ---- settlements (acerto de dívidas) ----
    op.create_table(
        'settlement',
        sa.Column('id', sa.Integer(), primary_key=True),
        sa.Column('workspace_id', sa.Integer(), sa.ForeignKey('workspace.id'), nullable=False),
        sa.Column('from_user_id', sa.Integer(), sa.ForeignKey('user.id'), nullable=False),
        sa.Column('to_user_id', sa.Integer(), sa.ForeignKey('user.id'), nullable=False),
        sa.Column('amount', sa.Numeric(20, 2), nullable=False),
        sa.Column('note', sa.String(), nullable=True),
        sa.Column('settled_at', sa.DateTime(), nullable=False),
        sa.Column('created_by_user_id', sa.Integer(), sa.ForeignKey('user.id'), nullable=True),
        sa.Column('created_at', sa.DateTime(), nullable=False),
        sa.Column('updated_at', sa.DateTime(), nullable=False),
        sa.Column('deleted_at', sa.DateTime(), nullable=True),
    )
    op.create_index('ix_settlement_workspace_id', 'settlement', ['workspace_id'])
    op.create_index('ix_settlement_from_user_id', 'settlement', ['from_user_id'])
    op.create_index('ix_settlement_to_user_id', 'settlement', ['to_user_id'])

    # ---- attachments (recibos no banco) ----
    op.create_table(
        'attachment',
        sa.Column('id', sa.Integer(), primary_key=True),
        sa.Column('workspace_id', sa.Integer(), sa.ForeignKey('workspace.id'), nullable=False),
        sa.Column('transaction_id', sa.Integer(), sa.ForeignKey('transaction.id'), nullable=False),
        sa.Column('filename', sa.String(), nullable=False),
        sa.Column('content_type', sa.String(), nullable=False),
        sa.Column('size_bytes', sa.Integer(), nullable=False),
        sa.Column('data', sa.LargeBinary(), nullable=False),
        sa.Column('uploaded_by_user_id', sa.Integer(), sa.ForeignKey('user.id'), nullable=True),
        sa.Column('created_at', sa.DateTime(), nullable=False),
    )
    op.create_index('ix_attachment_workspace_id', 'attachment', ['workspace_id'])
    op.create_index('ix_attachment_transaction_id', 'attachment', ['transaction_id'])

    # ---- tags ----
    op.create_table(
        'tag',
        sa.Column('id', sa.Integer(), primary_key=True),
        sa.Column('workspace_id', sa.Integer(), sa.ForeignKey('workspace.id'), nullable=False),
        sa.Column('name', sa.String(), nullable=False),
        sa.Column('color', sa.String(), nullable=True),
        sa.Column('created_at', sa.DateTime(), nullable=False),
        sa.Column('updated_at', sa.DateTime(), nullable=False),
        sa.Column('deleted_at', sa.DateTime(), nullable=True),
        sa.UniqueConstraint('workspace_id', 'name', name='uq_tag_workspace_name'),
    )
    op.create_index('ix_tag_workspace_id', 'tag', ['workspace_id'])

    op.create_table(
        'transactiontaglink',
        sa.Column('transaction_id', sa.Integer(), sa.ForeignKey('transaction.id'), primary_key=True),
        sa.Column('tag_id', sa.Integer(), sa.ForeignKey('tag.id'), primary_key=True),
    )

    # ---- recorrência: frequência semanal/anual ----
    op.add_column(
        'recurringexpense',
        sa.Column('frequency', _frequency_type(), nullable=False, server_default='monthly'),
    )
    op.add_column('recurringexpense', sa.Column('day_of_week', sa.Integer(), nullable=True))
    op.add_column('recurringexpense', sa.Column('month_of_year', sa.Integer(), nullable=True))

    # ---- parcelamento no cartão ----
    op.add_column('transaction', sa.Column('installment_no', sa.Integer(), nullable=True))
    op.add_column('transaction', sa.Column('installments_of', sa.Integer(), nullable=True))
    op.add_column('transaction', sa.Column('installment_group_id', sa.String(), nullable=True))
    op.create_index('ix_transaction_installment_group_id', 'transaction', ['installment_group_id'])


def downgrade() -> None:
    op.drop_index('ix_transaction_installment_group_id', table_name='transaction')
    with op.batch_alter_table('transaction') as batch_op:
        batch_op.drop_column('installment_group_id')
        batch_op.drop_column('installments_of')
        batch_op.drop_column('installment_no')

    with op.batch_alter_table('recurringexpense') as batch_op:
        batch_op.drop_column('month_of_year')
        batch_op.drop_column('day_of_week')
        batch_op.drop_column('frequency')

    op.drop_table('transactiontaglink')
    op.drop_index('ix_tag_workspace_id', table_name='tag')
    op.drop_table('tag')

    op.drop_index('ix_attachment_transaction_id', table_name='attachment')
    op.drop_index('ix_attachment_workspace_id', table_name='attachment')
    op.drop_table('attachment')

    op.drop_index('ix_settlement_to_user_id', table_name='settlement')
    op.drop_index('ix_settlement_from_user_id', table_name='settlement')
    op.drop_index('ix_settlement_workspace_id', table_name='settlement')
    op.drop_table('settlement')

    if _is_postgres():
        postgresql.ENUM(name='recurrencefrequency').drop(op.get_bind(), checkfirst=True)
