"""Unicidade de categoria e de orçamento por mês

- uq_category_workspace_name: `Tag` e `PaymentAccount` já tinham a unique
  equivalente; `Category` só tinha a checagem em Python, então duas requisições
  simultâneas criavam a mesma categoria duas vezes.

- uq_estimate_workspace_category_month: o orçamento era idempotente pelo RÓTULO
  de texto (`category`) e não pela FK (`category_id`) — com texto vazio/constante
  todos os orçamentos do mês colapsavam num só; com textos diferentes para a
  mesma categoria, duplicavam. A rota passou a chavear por category_id; aqui o
  banco garante.

Ambas deduplicam antes de criar o índice (sobrevive a menor id, por ser a que os
lançamentos mais antigos referenciam).

Revision ID: f4a8d21c93e7
Revises: e7c2a4f19b83
Create Date: 2026-07-26
"""
from alembic import op
import sqlalchemy as sa

revision = 'f4a8d21c93e7'
down_revision = 'e7c2a4f19b83'
branch_labels = None
depends_on = None


def _dedupe_categories(bind) -> None:
    """Aponta os usos da categoria duplicada para a sobrevivente e remove o resto."""
    duplicadas = bind.execute(sa.text("""
        SELECT c.id AS morta, k.keep_id
        FROM category c
        JOIN (
            SELECT workspace_id, name, MIN(id) AS keep_id
            FROM category
            GROUP BY workspace_id, name
            HAVING COUNT(*) > 1
        ) k ON k.workspace_id = c.workspace_id AND k.name = c.name
        WHERE c.id <> k.keep_id
    """)).fetchall()
    for morta, keep_id in duplicadas:
        # Não pode restar FK apontando para a linha que vai sumir
        for tabela in ("transactionitem", "recurringexpense", "monthlyestimate"):
            bind.execute(
                sa.text(f"UPDATE {tabela} SET category_id = :keep WHERE category_id = :morta"),
                {"keep": keep_id, "morta": morta},
            )
        bind.execute(sa.text("DELETE FROM category WHERE id = :morta"), {"morta": morta})


def _dedupe_estimates(bind) -> None:
    bind.execute(sa.text("""
        DELETE FROM monthlyestimate
        WHERE id NOT IN (
            SELECT keep_id FROM (
                SELECT MIN(id) AS keep_id
                FROM monthlyestimate
                GROUP BY workspace_id, category_id, month
            ) survivors
        )
    """))


def upgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    tables = set(inspector.get_table_names())

    if 'category' in tables:
        existing = {ix['name'] for ix in inspector.get_indexes('category')}
        if 'uq_category_workspace_name' not in existing:
            _dedupe_categories(bind)
            op.create_index(
                'uq_category_workspace_name', 'category',
                ['workspace_id', 'name'], unique=True,
            )

    if 'monthlyestimate' in tables:
        existing = {ix['name'] for ix in inspector.get_indexes('monthlyestimate')}
        if 'uq_estimate_workspace_category_month' not in existing:
            _dedupe_estimates(bind)
            # category_id NULL = orçamento "geral": NULLs são distintos na unique,
            # então vários gerais no mesmo mês continuam possíveis (é a rota que
            # os reaproveita, não o banco).
            op.create_index(
                'uq_estimate_workspace_category_month', 'monthlyestimate',
                ['workspace_id', 'category_id', 'month'], unique=True,
            )


def downgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    tables = set(inspector.get_table_names())

    if 'monthlyestimate' in tables:
        if 'uq_estimate_workspace_category_month' in {
            ix['name'] for ix in inspector.get_indexes('monthlyestimate')
        }:
            op.drop_index('uq_estimate_workspace_category_month', table_name='monthlyestimate')

    if 'category' in tables:
        if 'uq_category_workspace_name' in {
            ix['name'] for ix in inspector.get_indexes('category')
        }:
            op.drop_index('uq_category_workspace_name', table_name='category')
