"""Onda A: invariantes de unicidade que faltavam (renda recorrente e membership)

Duas invariantes existiam só em Python (lê-depois-escreve) e por isso não
sobreviviam a requisições concorrentes:

- uq_recurring_income_occurrence (income): a despesa recorrente já era protegida
  por `uq_recurring_occurrence`, mas a renda recorrente não tinha equivalente.
  Como a materialização roda a partir de ROTAS DE LEITURA (ensure_and_commit em
  GET /income, /analytics/summary, /analytics/reports), duas requisições
  simultâneas materializavam o mesmo salário duas vezes — e ele entrava em dobro
  em total_income/my_income/net_savings e na previsão.

- uq_membership_workspace_user (workspacemembership): três caminhos inserem
  membership (registro com convite pendente, convite a usuário existente e
  aceite de link) sem serialização. Membership duplicada inflava member_count e,
  pior, fazia get_workspace_membership resolver o PAPEL com .first() de forma
  não-determinística.

Ambas são precedidas de deduplicação, senão o upgrade falharia num banco que já
acumulou duplicatas. Índice único (não constraint) pelo mesmo motivo do
uq_recurring_occurrence: no SQLite a constraint exige rebuild da tabela.

Revision ID: d3b7f1a86c40
Revises: a2d5e8c31b76
Create Date: 2026-07-25
"""
from alembic import op
import sqlalchemy as sa

revision = 'd3b7f1a86c40'
down_revision = 'a2d5e8c31b76'
branch_labels = None
depends_on = None


# Nível hierárquico do papel em SQL — espelha role_level() de models/workspace.py.
# Usado na deduplicação para manter SEMPRE a linha de maior privilégio (perder
# permissão silenciosamente seria pior que a duplicata).
_ROLE_LEVEL_SQL = (
    "CASE role WHEN 'owner' THEN 3 WHEN 'admin' THEN 2 "
    "WHEN 'member' THEN 1 ELSE 0 END"
)


def _dedupe_income(bind) -> None:
    """Remove rendas recorrentes duplicadas por (recurring_income_id, received_at).

    Preferência de sobrevivente: a linha VIVA de menor id; se todas estiverem
    soft-deleted, a de menor id. Assim a renda que o usuário vê é preservada, e
    o tombstone (que bloqueia recriação) é preservado quando foi essa a intenção.
    """
    bind.execute(sa.text("""
        DELETE FROM income
        WHERE recurring_income_id IS NOT NULL
          AND id NOT IN (
            SELECT keep_id FROM (
              SELECT COALESCE(
                       MIN(CASE WHEN deleted_at IS NULL THEN id END),
                       MIN(id)
                     ) AS keep_id
              FROM income
              WHERE recurring_income_id IS NOT NULL
              GROUP BY recurring_income_id, received_at
            ) survivors
          )
    """))


def _dedupe_membership(bind) -> None:
    """Remove memberships duplicadas por (workspace_id, user_id).

    Sobrevivente: a de MAIOR papel; empatando, a de menor id.
    """
    bind.execute(sa.text(f"""
        DELETE FROM workspacemembership
        WHERE id NOT IN (
          SELECT keep_id FROM (
            SELECT MIN(m.id) AS keep_id
            FROM workspacemembership m
            JOIN (
              SELECT workspace_id, user_id, MAX({_ROLE_LEVEL_SQL}) AS lvl
              FROM workspacemembership
              GROUP BY workspace_id, user_id
            ) mx
              ON mx.workspace_id = m.workspace_id
             AND mx.user_id = m.user_id
             AND {_ROLE_LEVEL_SQL.replace('role', 'm.role')} = mx.lvl
            GROUP BY m.workspace_id, m.user_id
          ) survivors
        )
    """))


def upgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    tables = set(inspector.get_table_names())

    if 'income' in tables:
        existing = {ix['name'] for ix in inspector.get_indexes('income')}
        if 'uq_recurring_income_occurrence' not in existing:
            _dedupe_income(bind)
            # NULLs são distintos na unique → renda avulsa (sem recorrência) não colide
            op.create_index(
                'uq_recurring_income_occurrence', 'income',
                ['recurring_income_id', 'received_at'], unique=True,
            )

    if 'workspacemembership' in tables:
        existing = {ix['name'] for ix in inspector.get_indexes('workspacemembership')}
        if 'uq_membership_workspace_user' not in existing:
            _dedupe_membership(bind)
            op.create_index(
                'uq_membership_workspace_user', 'workspacemembership',
                ['workspace_id', 'user_id'], unique=True,
            )


def downgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    tables = set(inspector.get_table_names())

    if 'workspacemembership' in tables:
        existing = {ix['name'] for ix in inspector.get_indexes('workspacemembership')}
        if 'uq_membership_workspace_user' in existing:
            op.drop_index('uq_membership_workspace_user', table_name='workspacemembership')

    if 'income' in tables:
        existing = {ix['name'] for ix in inspector.get_indexes('income')}
        if 'uq_recurring_income_occurrence' in existing:
            op.drop_index('uq_recurring_income_occurrence', table_name='income')
