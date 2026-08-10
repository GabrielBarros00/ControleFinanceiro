"""Acrescenta `daily` ao enum recurrencefrequency no Postgres

O enum nasceu em `a9c4e72d18f3` com `('weekly', 'monthly', 'yearly')`. Depois
`RecurrenceFrequency.daily` entrou no modelo — e no motor de ocorrências, que
trata diária junto com semanal — mas **nenhuma migração estendeu o tipo**. O
resultado, só no Postgres:

    invalid input value for enum recurrencefrequency: "daily"

Ou seja: cadastrar uma recorrência DIÁRIA falhava com 500 em produção. Em
desenvolvimento não: o SQLite não tem tipo enum e aceita a string.

Por que passou despercebido tanto tempo — três redes, todas cegas para isto:

- a suíte roda em SQLite por padrão, onde o enum não existe;
- `alembic check` compara TABELAS e COLUNAS, não os rótulos de um enum já criado,
  então "sem drift" era verdade e insuficiente;
- no leg Postgres do CI, o `create_all` dos testes encontra o tipo já criado pela
  migração e não o recria (`checkfirst`), então a divergência sobrevive.

`ADD VALUE` não pode rodar dentro do bloco transacional da migração, daí o
`autocommit_block`. `IF NOT EXISTS` torna a migração idempotente para quem já
tiver corrigido o tipo à mão.

Revision ID: e9b2c50d7a14
Revises: d8f1a37c025b
Create Date: 2026-08-10
"""
from alembic import op

revision = 'e9b2c50d7a14'
down_revision = 'd8f1a37c025b'
branch_labels = None
depends_on = None


def upgrade() -> None:
    bind = op.get_bind()
    if bind.dialect.name != "postgresql":
        # SQLite guarda o enum como texto: nada a alterar.
        return
    # `BEFORE 'weekly'` só para a ordem do tipo espelhar a do modelo — o valor
    # funcionaria igual no fim da lista.
    with op.get_context().autocommit_block():
        op.execute(
            "ALTER TYPE recurrencefrequency ADD VALUE IF NOT EXISTS 'daily' BEFORE 'weekly'"
        )


def downgrade() -> None:
    # Postgres não remove valor de enum sem recriar o tipo inteiro, e recriá-lo
    # exigiria reescrever todas as colunas que o usam — risco alto para desfazer
    # uma correção. Um valor a mais no tipo não quebra nada.
    pass
