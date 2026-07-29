"""notification.type: VARCHAR -> enum nativo no Postgres

A migração das notificações (`a5e9c37f2b10`) criou `notification.type` como
`sa.String()`, mas o modelo declara `NotificationType` (enum). No SQLite isso é
invisível — enum vira texto de qualquer jeito. No **Postgres** o `alembic check`
acusa `modify_type VARCHAR -> Enum(...)`, e ele é step obrigatório do job
`backend-postgres` no CI: ou seja, a cadeia do-zero estava com drift.

Mesmo remédio (e mesmo DO-block idempotente por `udt_name`) da reconciliação
`a1f7c3e9d024`, que já converteu três colunas na mesma situação. O tipo
`notificationtype` pode não existir ainda: como a coluna nasceu VARCHAR, o
SQLAlchemy nunca chegou a emitir o CREATE TYPE.

Revision ID: c1b7e0a4d386
Revises: b6d4f28a9c15
Create Date: 2026-07-29
"""
from alembic import op
import sqlalchemy as sa

revision = 'c1b7e0a4d386'
down_revision = 'b6d4f28a9c15'
branch_labels = None
depends_on = None

_VALORES = ("workspace_invite", "member_added", "invite_revoked")


def upgrade() -> None:
    bind = op.get_bind()
    if bind.dialect.name != "postgresql":
        return  # SQLite guarda enum como texto: nada a fazer

    valores = ", ".join(f"'{v}'" for v in _VALORES)
    op.execute(f"""
    DO $$ BEGIN
      IF NOT EXISTS (SELECT 1 FROM pg_type WHERE typname = 'notificationtype') THEN
        CREATE TYPE notificationtype AS ENUM ({valores});
      END IF;
      IF (SELECT udt_name FROM information_schema.columns
          WHERE table_name='notification' AND column_name='type') = 'varchar' THEN
        ALTER TABLE notification ALTER COLUMN type
          TYPE notificationtype USING type::notificationtype;
      END IF;
    END $$;
    """)


def downgrade() -> None:
    bind = op.get_bind()
    if bind.dialect.name != "postgresql":
        return
    op.execute("""
    DO $$ BEGIN
      IF (SELECT udt_name FROM information_schema.columns
          WHERE table_name='notification' AND column_name='type') <> 'varchar' THEN
        ALTER TABLE notification ALTER COLUMN type TYPE varchar USING type::text;
      END IF;
    END $$;
    """)
