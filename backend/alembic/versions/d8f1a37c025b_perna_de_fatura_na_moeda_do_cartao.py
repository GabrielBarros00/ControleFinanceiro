"""A perna de FATURA do lançamento, na moeda do cartão (ADR 0024)

`Transaction.currency`/`total_amount` são a moeda-base do WORKSPACE. A fatura,
porém, é cobrada na moeda do CARTÃO — que desde o ADR 0021 é pessoal e nasce na
moeda de relatório do dono, sem relação nenhuma com a base do workspace onde a
compra foi feita. Enquanto existiu um valor só, `compute_statement_total`
filtrava `currency == card.currency`, não achava linha nenhuma, e um cartão em
USD usado num workspace em BRL somava R$ 0,00 com as compras listadas na tela: o
limite nunca era consumido e o fechamento congelava o zero como histórico.

O backfill é IDENTIDADE, de propósito: `statement_amount = total_amount` e
`statement_currency = currency`. Isso acerta o caso são — cartão e workspace na
mesma moeda, a esmagadora maioria — e **não inventa conversão retroativa**, na
linha do ADR 0015 ("o valor é congelado na entrada, de propósito"). Reconverter
aqui produziria um número que banco nenhum cobrou, com a cotação de hoje sobre
uma compra de meses atrás.

As linhas realmente divergentes continuam fora do total, mas deixam de ser
silenciosas: `excluded_from_total_count` as conta na API e a fatura avisa. Quem
quiser a conversão histórica roda `scripts/backfill_statement_amounts.py`, que
usa a taxa da data de cada compra e falha alto quando ela não existe.

Revision ID: d8f1a37c025b
Revises: c7e3b81f04a9
Create Date: 2026-08-10
"""
from alembic import op
import sqlalchemy as sa

revision = 'd8f1a37c025b'
down_revision = 'c7e3b81f04a9'
branch_labels = None
depends_on = None


def upgrade() -> None:
    # `transaction` é palavra reservada nos dois dialetos — daí as aspas no SQL.
    with op.batch_alter_table("transaction") as batch:
        batch.add_column(sa.Column("statement_amount", sa.Numeric(20, 2), nullable=True))
        batch.add_column(sa.Column("statement_currency", sa.String(), nullable=True))
        batch.add_column(
            sa.Column("statement_exchange_rate", sa.Numeric(20, 6), nullable=True)
        )

    op.execute(sa.text(
        'UPDATE "transaction" '
        "SET statement_amount = total_amount, "
        "    statement_currency = currency, "
        "    statement_exchange_rate = 1 "
        "WHERE statement_id IS NOT NULL"
    ))


def downgrade() -> None:
    with op.batch_alter_table("transaction") as batch:
        batch.drop_column("statement_exchange_rate")
        batch.drop_column("statement_currency")
        batch.drop_column("statement_amount")
