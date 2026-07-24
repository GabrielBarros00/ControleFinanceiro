"""Reconciliação de drift: FKs, constraint redundante e tipos enum

`alembic check` acusava drift entre os models e as migrações — invisível à
suíte porque os testes montam o schema via create_all dos models, nunca pelas
migrações (e no SQLite, que não tem tipo ENUM nem enforce FK, várias
divergências nem aparecem). Esta migração alinha o banco migrado aos models:

- Adiciona 4 FKs que os models declaram mas nenhuma migração criava. As colunas
  já existiam; faltava só a integridade referencial (no Postgres de produção as
  constraints simplesmente não existiam):
    income.recurring_income_id      -> recurringincome.id
    monthlyestimate.category_id     -> category.id
    recurringexpense.category_id    -> category.id
    recurringexpense.payer_user_id  -> user.id
- Remove a UNIQUE constraint redundante uq_refreshsession_jti — o índice único
  ix_refreshsession_jti já garante a unicidade do jti (o model só declara o
  índice).
- Converte 3 colunas enum que migrações antigas criaram como VARCHAR, enquanto
  as colunas irmãs viraram ENUM nativo (só no Postgres; os tipos já existem):
    recurringexpense.payment_method -> paymentmethod
    transactionpayer.payment_method -> paymentmethod
    recurringincome.frequency       -> recurrencefrequency

A divergência do uq_recurring_occurrence (índice único no banco vs
UniqueConstraint no model) foi resolvida do lado do model (passou a Index
unique), então não há operação de banco para ela aqui.

Idempotente: cada operação confere o estado atual antes de agir. batch_alter_table
= ALTER direto no Postgres, recreate no SQLite (onde FK não é enforced, seguro).
As conversões de enum só rodam no Postgres (o SQLite guarda enum como texto).

Revision ID: a1f7c3e9d024
Revises: d4e6f8a0c315
Create Date: 2026-07-24
"""
from collections import OrderedDict

from alembic import op
import sqlalchemy as sa

revision = 'a1f7c3e9d024'
down_revision = 'd4e6f8a0c315'
branch_labels = None
depends_on = None


# (table, constraint_name, referent_table, local_cols, remote_cols)
_FKS = [
    ("income", "fk_income_recurring_income_id", "recurringincome", ["recurring_income_id"], ["id"]),
    ("monthlyestimate", "fk_monthlyestimate_category_id", "category", ["category_id"], ["id"]),
    ("recurringexpense", "fk_recurringexpense_category_id", "category", ["category_id"], ["id"]),
    ("recurringexpense", "fk_recurringexpense_payer_user_id", "user", ["payer_user_id"], ["id"]),
]


def _has_fk(inspector, table, local_cols):
    target = set(local_cols)
    return any(
        set(fk.get("constrained_columns") or []) == target
        for fk in inspector.get_foreign_keys(table)
    )


def _has_unique(inspector, table, name):
    return any(uc.get("name") == name for uc in inspector.get_unique_constraints(table))


def _pg_varchar_to_enum(table, column, enum_type, *, default=None):
    """Converte VARCHAR -> enum nativo no Postgres, só se ainda for varchar.
    Preserva o server default (drop/cast/set) quando informado."""
    set_default = f"ALTER TABLE {table} ALTER COLUMN {column} SET DEFAULT '{default}';" if default else ""
    drop_default = f"ALTER TABLE {table} ALTER COLUMN {column} DROP DEFAULT;" if default else ""
    op.execute(f"""
    DO $$ BEGIN
      IF (SELECT udt_name FROM information_schema.columns
          WHERE table_name='{table}' AND column_name='{column}') = 'varchar' THEN
        {drop_default}
        ALTER TABLE {table} ALTER COLUMN {column}
          TYPE {enum_type} USING {column}::{enum_type};
        {set_default}
      END IF;
    END $$;
    """)


def _pg_enum_to_varchar(table, column, *, default=None):
    set_default = f"ALTER TABLE {table} ALTER COLUMN {column} SET DEFAULT '{default}';" if default else ""
    drop_default = f"ALTER TABLE {table} ALTER COLUMN {column} DROP DEFAULT;" if default else ""
    op.execute(f"""
    DO $$ BEGIN
      IF (SELECT udt_name FROM information_schema.columns
          WHERE table_name='{table}' AND column_name='{column}') <> 'varchar' THEN
        {drop_default}
        ALTER TABLE {table} ALTER COLUMN {column} TYPE varchar USING {column}::text;
        {set_default}
      END IF;
    END $$;
    """)


def upgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)

    # --- FKs faltantes (agrupadas por tabela: 1 recreate por tabela no SQLite) ---
    by_table = OrderedDict()
    for table, name, ref, local, remote in _FKS:
        by_table.setdefault(table, []).append((name, ref, local, remote))

    for table, fks in by_table.items():
        to_add = [(n, r, loc, rem) for (n, r, loc, rem) in fks if not _has_fk(inspector, table, loc)]
        if to_add:
            with op.batch_alter_table(table) as batch_op:
                for name, ref, local, remote in to_add:
                    batch_op.create_foreign_key(name, ref, local, remote)

    # --- Constraint unique redundante em refreshsession.jti ---
    if _has_unique(inspector, "refreshsession", "uq_refreshsession_jti"):
        with op.batch_alter_table("refreshsession") as batch_op:
            batch_op.drop_constraint("uq_refreshsession_jti", type_="unique")

    # --- Colunas enum criadas como VARCHAR (só Postgres; tipos já existem) ---
    if bind.dialect.name == "postgresql":
        _pg_varchar_to_enum("recurringexpense", "payment_method", "paymentmethod")
        _pg_varchar_to_enum("transactionpayer", "payment_method", "paymentmethod")
        _pg_varchar_to_enum("recurringincome", "frequency", "recurrencefrequency", default="monthly")


def downgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)

    if bind.dialect.name == "postgresql":
        _pg_enum_to_varchar("recurringincome", "frequency", default="monthly")
        _pg_enum_to_varchar("transactionpayer", "payment_method")
        _pg_enum_to_varchar("recurringexpense", "payment_method")

    if not _has_unique(inspector, "refreshsession", "uq_refreshsession_jti"):
        with op.batch_alter_table("refreshsession") as batch_op:
            batch_op.create_unique_constraint("uq_refreshsession_jti", ["jti"])

    for table, name, ref, local, remote in reversed(_FKS):
        if _has_fk(inspector, table, local):
            with op.batch_alter_table(table) as batch_op:
                batch_op.drop_constraint(name, type_="foreignkey")
