"""Normaliza e-mails para caixa baixa (usuários e convites)

`User.email` é unique na string CRUA, então `Joao@x.com` e `joao@x.com` eram
duas contas distintas. Consequências no dia a dia: convite enviado para uma
grafia era recusado para a outra (`invite.email != current_user.email`), o
`forgot-password` não encontrava a conta e respondia o genérico "se o email
estiver cadastrado" — deixando a pessoa sem saída.

A partir daqui a normalização é feita na ENTRADA (schemas/common.NormalizedEmail);
esta migração acerta o que já está gravado.

COLISÕES: se duas contas diferirem só pela caixa, a migração ABORTA com a lista.
Fundir contas automaticamente é destrutivo (qual senha vale? de quem são os
lançamentos?) e precisa de decisão humana.

Revision ID: e7c2a4f19b83
Revises: d3b7f1a86c40
Create Date: 2026-07-26
"""
from alembic import op
import sqlalchemy as sa

revision = 'e7c2a4f19b83'
down_revision = 'd3b7f1a86c40'
branch_labels = None
depends_on = None


class EmailCollision(Exception):
    """Contas que só diferem pela caixa — exige decisão humana."""


def upgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    tables = set(inspector.get_table_names())

    if 'user' in tables:
        colisoes = bind.execute(sa.text("""
            SELECT LOWER(email) AS normalizado, COUNT(*) AS total
            FROM "user"
            GROUP BY LOWER(email)
            HAVING COUNT(*) > 1
        """)).fetchall()
        if colisoes:
            detalhes = ", ".join(f"{row[0]} ({row[1]} contas)" for row in colisoes)
            raise EmailCollision(
                "Não é possível normalizar os e-mails: existem contas que diferem "
                f"apenas pela caixa — {detalhes}. Decida manualmente qual conta "
                "permanece (migre os dados da outra e desative-a) e rode a "
                "migração de novo."
            )
        bind.execute(sa.text('UPDATE "user" SET email = LOWER(TRIM(email)) WHERE email <> LOWER(TRIM(email))'))

    if 'workspaceinvite' in tables:
        # Convite por link tem email NULL — o WHERE já o ignora
        bind.execute(sa.text(
            "UPDATE workspaceinvite SET email = LOWER(TRIM(email)) "
            "WHERE email IS NOT NULL AND email <> LOWER(TRIM(email))"
        ))


def downgrade() -> None:
    # Normalização não é reversível: a caixa original não é recuperável.
    pass
