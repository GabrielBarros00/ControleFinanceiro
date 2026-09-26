"""Item da nota com medida: unidade e preço unitário com 4 casas (ADR 0040)

- `transactionitem.unit`: anulável (item-sombra e linhas antigas não têm medida);
  o vocabulário (`un`, `kg`, `g`, `l`, `ml`, `m`) é conferido na aplicação, não
  por enum do Postgres — valor novo num enum exige `ALTER TYPE` à mão, e nem o
  SQLite nem o `alembic check` o enxergam.
- `transactionitem.unit_amount`: `Numeric(20,2)` → `Numeric(20,4)`. Ampliar a
  escala não perde dado: 25.00 vira 25.0000. Com 2 casas, o Postgres arredondava
  em silêncio o preço de R$ 5,899 do litro para 5,90.

Upgrade idempotente (o DDL do SQLite não é transacional). O downgrade volta a
escala para 2 casas — e ARREDONDA o que tiver mais —, e remove a unidade.

Revision ID: f4b8d2c6a1e3
Revises: e5a9c2d4b7f1
Create Date: 2026-09-26
"""
from alembic import op
import sqlalchemy as sa

revision = 'f4b8d2c6a1e3'
down_revision = 'e5a9c2d4b7f1'
branch_labels = None
depends_on = None


def upgrade() -> None:
    colunas = {c["name"] for c in sa.inspect(op.get_bind()).get_columns("transactionitem")}
    if "unit" not in colunas:
        op.add_column("transactionitem", sa.Column("unit", sa.String(length=8), nullable=True))
    with op.batch_alter_table("transactionitem") as lote:
        lote.alter_column(
            "unit_amount",
            existing_type=sa.Numeric(20, 2),
            type_=sa.Numeric(20, 4),
            existing_nullable=True,
        )


def downgrade() -> None:
    with op.batch_alter_table("transactionitem") as lote:
        lote.alter_column(
            "unit_amount",
            existing_type=sa.Numeric(20, 4),
            type_=sa.Numeric(20, 2),
            existing_nullable=True,
        )
        lote.drop_column("unit")
