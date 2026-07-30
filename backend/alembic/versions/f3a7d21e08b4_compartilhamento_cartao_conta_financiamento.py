"""Cartão, conta e financiamento compartilháveis entre workspaces (ADR 0019)

Sem compartilhamento, usar o MESMO cartão em dois workspaces exigia cadastrá-lo
duas vezes — e cada cópia gerava a sua fatura, então a mesma dívida aparecia dois
lugares no Endividamento e na Previsão. O mesmo valia para a conta de onde o
dinheiro sai e para o financiamento do imóvel do casal.

`CardWorkspaceAccess.access` separa **usar** de **devassar**: com `use`, o
workspace lança compras no cartão e vê o subtotal DELE; limite e fatura inteira
continuam sendo do dono. Era a granularidade que faltava na Onda 1, em que
enxergar o cartão (por ter uma compra nele) trazia o limite do dono junto.

**Sem backfill.** O cartão/conta/financiamento existente continua pertencendo ao
seu workspace e visível lá exatamente como antes — compartilhar é ato explícito.
Semear vínculos aqui ofereceria dados de uma pessoa a workspaces que ela nunca
escolheu.

Revision ID: f3a7d21e08b4
Revises: e1c9b482f57a
Create Date: 2026-07-30
"""
from alembic import op
import sqlalchemy as sa

revision = 'f3a7d21e08b4'
down_revision = 'e1c9b482f57a'
branch_labels = None
depends_on = None

# (tabela, coluna FK, tabela referenciada, nome da unique)
_VINCULOS = (
    ('cardworkspaceaccess', 'card_id', 'creditcard', 'uq_card_access_card_workspace'),
    (
        'paymentaccountworkspaceshare',
        'account_id',
        'paymentaccount',
        'uq_account_share_account_workspace',
    ),
    (
        'financingworkspaceshare',
        'financing_id',
        'financing',
        'uq_financing_share_financing_workspace',
    ),
)


def upgrade() -> None:
    bind = op.get_bind()
    existentes = set(sa.inspect(bind).get_table_names())

    for tabela, fk, referencia, unique in _VINCULOS:
        if tabela in existentes:
            continue
        colunas = [
            sa.Column('id', sa.Integer(), primary_key=True, nullable=False),
            sa.Column(fk, sa.Integer(), nullable=False),
            sa.Column('workspace_id', sa.Integer(), nullable=False),
        ]
        # Só o cartão tem nível de acesso: conta e financiamento são "compartilha
        # ou não". Inventar um enum para os três seria complexidade sem uso.
        if tabela == 'cardworkspaceaccess':
            colunas.append(
                sa.Column(
                    'access', sa.String(length=10), nullable=False, server_default='use'
                )
            )
        colunas.extend([
            sa.Column('created_at', sa.DateTime(), nullable=False),
            sa.ForeignKeyConstraint([fk], [f'{referencia}.id']),
            sa.ForeignKeyConstraint(['workspace_id'], ['workspace.id']),
            sa.UniqueConstraint(fk, 'workspace_id', name=unique),
        ])
        op.create_table(tabela, *colunas)
        op.create_index(f'ix_{tabela}_{fk}', tabela, [fk])
        op.create_index(f'ix_{tabela}_workspace_id', tabela, ['workspace_id'])


def downgrade() -> None:
    bind = op.get_bind()
    existentes = set(sa.inspect(bind).get_table_names())
    for tabela, _fk, _ref, _unique in _VINCULOS:
        if tabela in existentes:
            op.drop_table(tabela)
