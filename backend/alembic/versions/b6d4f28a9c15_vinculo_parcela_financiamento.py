"""Vínculo por ID entre a despesa e a parcela de financiamento

`unpay_installment` desfazia o pagamento procurando a despesa pelo TÍTULO
(`f"{financing.title} — Parcela {n}/{N}"`) e soft-deletando TODA transação viva
do workspace com aquela string. Duas falhas nisso:

1. Renomear o financiamento (permitido, e sem trava com parcelas pagas) fazia o
   estorno não encontrar nada — a despesa ficava para sempre no caixa e nos
   relatórios, com a parcela já marcada como aberta.
2. Uma despesa manual com o mesmo título era apagada junto.

`transaction.financing_installment_id` dá a identidade que faltava. Nullable
porque só as despesas geradas por pagamento de parcela a têm; as linhas legadas
ficam com NULL e continuam sendo tratadas pelo fallback de título na rota.

A FK vai por `batch_alter_table` (mesmo padrão de a1f7c3e9d024): ALTER direto no
Postgres, recriação da tabela no SQLite.

Revision ID: b6d4f28a9c15
Revises: a5e9c37f2b10
Create Date: 2026-07-29
"""
from alembic import op
import sqlalchemy as sa

revision = 'b6d4f28a9c15'
down_revision = 'a5e9c37f2b10'
branch_labels = None
depends_on = None

_COLUNA = 'financing_installment_id'
_INDICE = 'ix_transaction_financing_installment_id'
_FK = 'fk_transaction_financing_installment_id'


def _tem_coluna(inspector) -> bool:
    return _COLUNA in {c['name'] for c in inspector.get_columns('transaction')}


def upgrade() -> None:
    inspector = sa.inspect(op.get_bind())
    if _tem_coluna(inspector):
        return

    op.add_column('transaction', sa.Column(_COLUNA, sa.Integer(), nullable=True))
    op.create_index(_INDICE, 'transaction', [_COLUNA])
    with op.batch_alter_table('transaction') as batch:
        batch.create_foreign_key(
            _FK, 'amortizationinstallment', [_COLUNA], ['id']
        )


def downgrade() -> None:
    inspector = sa.inspect(op.get_bind())
    if not _tem_coluna(inspector):
        return
    with op.batch_alter_table('transaction') as batch:
        batch.drop_constraint(_FK, type_='foreignkey')
    op.drop_index(_INDICE, table_name='transaction')
    op.drop_column('transaction', _COLUNA)
