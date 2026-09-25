"""Assinaturas: marca, plano, fim do teste grátis e observações na recorrência (ADR 0039)

Colunas opcionais na `recurringexpense`. O período e a renovação não ganham
coluna: são a frequência e a próxima ocorrência da própria recorrência. O
provedor é o estabelecimento (`merchant_id`, ADR 0038).

Revision ID: e5a9c2d4b7f1
Revises: d7e4b2a9c518
Create Date: 2026-09-25
"""
from alembic import op
import sqlalchemy as sa

revision = 'e5a9c2d4b7f1'
down_revision = 'd7e4b2a9c518'
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column('recurringexpense', sa.Column('is_subscription', sa.Boolean(), nullable=False, server_default=sa.false()))
    op.add_column('recurringexpense', sa.Column('plan', sa.String(length=120), nullable=True))
    op.add_column('recurringexpense', sa.Column('trial_ends_on', sa.Date(), nullable=True))
    op.add_column('recurringexpense', sa.Column('notes', sa.String(length=1000), nullable=True))


def downgrade() -> None:
    with op.batch_alter_table('recurringexpense') as lote:
        lote.drop_column('notes')
        lote.drop_column('trial_ends_on')
        lote.drop_column('plan')
        lote.drop_column('is_subscription')
