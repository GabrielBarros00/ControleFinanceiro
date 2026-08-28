"""Aviso de vencimento: inscrição de push, dedupe e preferências (ADR 0033)

Três coisas, e uma delas é a que costuma ser esquecida.

1. `pushsubscription` — um par (pessoa, navegador) que aceitou receber aviso.
2. `duereminder` — o registro de "já avisei isto", com a restrição de unicidade
   que impede o job diário de reavisar a mesma conta todo dia.
3. `user.notify_*` — as preferências.

E a quarta, que não é tabela: **`notificationtype` é enum NATIVO no Postgres**
desde a revisão `c1b7e0a4d386`. Acrescentar `due_reminder` ao Enum do Python não
basta — sem o `ALTER TYPE` daqui, o INSERT do primeiro aviso estoura em produção
com `invalid input value for enum`. E não há gate que pegue isso: no SQLite enum
é texto, então a suíte inteira passa verde; o `alembic check` compara colunas,
não valores de enum.

Revision ID: e7a4c9b18d52
Revises: b3d9f21c74e8
Create Date: 2026-08-28
"""
import sqlalchemy as sa
from alembic import op

revision = 'e7a4c9b18d52'
down_revision = 'b3d9f21c74e8'
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        'pushsubscription',
        sa.Column('id', sa.Integer(), nullable=False),
        # `Text` e não `String(n)`: o tamanho do endpoint é escolha do serviço de
        # push (o do FCM já passa de 200 caracteres), não nossa.
        sa.Column('endpoint', sa.Text(), nullable=False),
        sa.Column('user_id', sa.Integer(), nullable=False),
        sa.Column('p256dh', sa.String(length=255), nullable=False),
        sa.Column('auth', sa.String(length=255), nullable=False),
        sa.Column('user_agent', sa.String(length=255), nullable=True),
        sa.Column('created_at', sa.DateTime(), nullable=False),
        sa.Column('last_success_at', sa.DateTime(), nullable=True),
        sa.ForeignKeyConstraint(['user_id'], ['user.id'], ),
        sa.PrimaryKeyConstraint('id'),
    )
    # Único: reinscrever no mesmo navegador devolve o MESMO endpoint. É o que
    # faz a linha mudar de dono quando outra pessoa ativa no mesmo aparelho, em
    # vez de duas pessoas receberem no mesmo lugar (ADR 0018).
    op.create_index('ix_pushsubscription_endpoint', 'pushsubscription', ['endpoint'], unique=True)
    op.create_index('ix_pushsubscription_user_id', 'pushsubscription', ['user_id'])

    op.create_table(
        'duereminder',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('user_id', sa.Integer(), nullable=False),
        # String e não Enum nativo, seguindo `User.platform_role`: valor novo num
        # enum do Postgres exige ALTER TYPE à mão — exatamente a armadilha que
        # esta migração precisa desarmar logo abaixo para o `notificationtype`.
        sa.Column('source', sa.String(length=20), nullable=False),
        sa.Column('source_id', sa.Integer(), nullable=False),
        sa.Column('milestone', sa.String(length=20), nullable=False),
        sa.Column('due_date', sa.Date(), nullable=False),
        sa.Column('created_at', sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(['user_id'], ['user.id'], ),
        sa.PrimaryKeyConstraint('id'),
        # A restrição que impede o spam — e que torna seguro rodar o job duas
        # vezes no mesmo dia (restart, deploy) sem trava nenhuma.
        sa.UniqueConstraint(
            'user_id', 'source', 'source_id', 'milestone', 'due_date',
            name='uq_duereminder_marco',
        ),
    )
    op.create_index('ix_duereminder_user_id', 'duereminder', ['user_id'])
    op.create_index('ix_duereminder_source_id', 'duereminder', ['source_id'])

    # `server_default` nos três: a coluna nasce NOT NULL numa tabela que já tem
    # linhas, e sem default o ALTER falha em qualquer banco com um usuário.
    op.add_column('user', sa.Column(
        'notify_days_before', sa.Integer(), nullable=False, server_default='3'))
    op.add_column('user', sa.Column(
        'notify_by_email', sa.Boolean(), nullable=False, server_default=sa.false()))
    op.add_column('user', sa.Column(
        'notify_show_amount', sa.Boolean(), nullable=False, server_default=sa.false()))

    _adicionar_valor_de_enum()


def _adicionar_valor_de_enum() -> None:
    """`due_reminder` no tipo `notificationtype`.

    `ADD VALUE IF NOT EXISTS` porque a migração precisa ser reexecutável, e
    porque o tipo pode não existir num banco que nunca passou pela
    `c1b7e0a4d386` (SQLite, ou Postgres criado por `create_all`).
    """
    bind = op.get_bind()
    if bind.dialect.name != 'postgresql':
        return  # SQLite guarda enum como texto: nada a fazer

    op.execute("""
    DO $$ BEGIN
      IF EXISTS (SELECT 1 FROM pg_type WHERE typname = 'notificationtype') THEN
        ALTER TYPE notificationtype ADD VALUE IF NOT EXISTS 'due_reminder';
      END IF;
    END $$;
    """)


def downgrade() -> None:
    op.drop_column('user', 'notify_show_amount')
    op.drop_column('user', 'notify_by_email')
    op.drop_column('user', 'notify_days_before')

    op.drop_index('ix_duereminder_source_id', table_name='duereminder')
    op.drop_index('ix_duereminder_user_id', table_name='duereminder')
    op.drop_table('duereminder')

    op.drop_index('ix_pushsubscription_user_id', table_name='pushsubscription')
    op.drop_index('ix_pushsubscription_endpoint', table_name='pushsubscription')
    op.drop_table('pushsubscription')

    # O valor do enum NÃO é removido de propósito: o Postgres não tem
    # `ALTER TYPE ... DROP VALUE`, e recriar o tipo exigiria reescrever a coluna
    # inteira. Um valor a mais no enum é inerte; a tentativa de removê-lo é que
    # derrubaria o downgrade.
