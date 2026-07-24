"""Reconciliação do drift modelos↔migrations

Alinha o schema das migrações aos models (revelado por `alembic check`):
- dropa tabelas legadas de RBAC (role/permission/rolepermissionlink) — hoje o
  RBAC é por `role_level`, essas tabelas não têm model e são schema morto;
- cria índices que os models declaram e faltavam;
- cria as FKs faltantes apenas no Postgres (onde são impostas e o ALTER é
  direto). No SQLite as FKs não são impostas por padrão e um rebuild via batch
  seria arriscado — por isso são puladas lá.

NOT NULL divergentes e diferença de FORMA da unique (índice × constraint) são
cosméticos e ficam para uma migração dedicada validada em staging Postgres.

Revision ID: a7b3c9d15e42
Revises: f1a2b3c4d5e6
Create Date: 2026-07-23
"""
from alembic import op
import sqlalchemy as sa

revision = 'a7b3c9d15e42'
down_revision = 'f1a2b3c4d5e6'
branch_labels = None
depends_on = None


# (tabela, coluna, tabela_ref, nome_da_fk)
_FKS = [
    ('income', 'recurring_income_id', 'recurringincome', 'fk_income_recurring_income_id'),
    ('monthlyestimate', 'category_id', 'category', 'fk_monthlyestimate_category_id'),
    ('recurringexpense', 'category_id', 'category', 'fk_recurringexpense_category_id'),
    ('recurringexpense', 'payer_user_id', 'user', 'fk_recurringexpense_payer_user_id'),
    ('transaction', 'statement_id', 'cardstatement', 'fk_transaction_statement_id'),
    ('transaction', 'credit_card_id', 'creditcard', 'fk_transaction_credit_card_id'),
    ('transactionitem', 'category_id', 'category', 'fk_transactionitem_category_id'),
]

# (tabela, nome_do_indice, colunas)
_INDEXES = [
    ('transaction', 'ix_transaction_credit_card_id', ['credit_card_id']),
    ('transaction', 'ix_transaction_statement_id', ['statement_id']),
    ('transaction', 'ix_transaction_payment_method', ['payment_method']),
    ('transaction', 'ix_transaction_installment_group_id', ['installment_group_id']),
    ('transactionitem', 'ix_transactionitem_category_id', ['category_id']),
]


def upgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    tables = set(inspector.get_table_names())

    # 1) Tabelas legadas de RBAC (substituídas por role_level) — schema morto
    for legacy in ('rolepermissionlink', 'role', 'permission'):
        if legacy in tables:
            op.drop_table(legacy)

    # 2) Índices declarados nos models e ausentes das migrações
    for table, name, cols in _INDEXES:
        if table not in tables:
            continue
        existing = {ix['name'] for ix in inspector.get_indexes(table)}
        if name not in existing:
            op.create_index(name, table, cols)

    # 3) FKs faltantes — só no Postgres (SQLite não impõe FK; rebuild é arriscado)
    if bind.dialect.name != 'sqlite':
        for table, col, ref_table, name in _FKS:
            if table not in tables:
                continue
            has = any(col in fk['constrained_columns'] for fk in inspector.get_foreign_keys(table))
            if not has:
                op.create_foreign_key(name, table, ref_table, [col], ['id'])


def downgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    tables = set(inspector.get_table_names())

    if bind.dialect.name != 'sqlite':
        for table, col, ref_table, name in _FKS:
            if table in tables:
                try:
                    op.drop_constraint(name, table, type_='foreignkey')
                except Exception:
                    pass

    for table, name, cols in _INDEXES:
        if table in tables:
            existing = {ix['name'] for ix in inspector.get_indexes(table)}
            if name in existing:
                op.drop_index(name, table_name=table)

    # As tabelas legadas de RBAC NÃO são recriadas (eram schema morto).
