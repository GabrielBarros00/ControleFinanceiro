"""Os enums do MODELO e os do banco têm de ter os mesmos rótulos.

O defeito que motivou este arquivo: `RecurrenceFrequency.daily` entrou no modelo
e no motor de ocorrências, mas nenhuma migração estendeu o tipo
`recurrencefrequency` do Postgres — criado em `a9c4e72d18f3` com apenas
`('weekly', 'monthly', 'yearly')`. Em produção, cadastrar uma recorrência diária
respondia 500:

    invalid input value for enum recurrencefrequency: "daily"

Três redes existiam e as três eram cegas para isto:

- a suíte roda em **SQLite** por padrão, que não tem tipo enum e aceita qualquer
  string — todo teste de recorrência diária passava;
- **`alembic check`** compara tabelas e colunas, não os rótulos de um enum que já
  existe: ele dizia "sem drift", e estava certo dentro do que olha;
- no leg Postgres do CI, o `create_all` da suíte encontra o tipo já criado pela
  migração e **não o recria** (`checkfirst`), então a divergência atravessa
  intacta.

Este teste fecha o vão de forma genérica: qualquer enum que ganhe um valor novo
no modelo sem a migração correspondente falha aqui, não em produção.
"""
import os

import pytest
from sqlmodel import Session

from tests.conftest import engine

# Só faz sentido onde o banco TEM tipos enumerados. No SQLite não há o que
# comparar — e é justamente por isso que o defeito sobreviveu.
so_no_postgres = pytest.mark.skipif(
    not os.environ.get("TEST_DATABASE_URL", "").startswith("postgresql"),
    reason="tipos ENUM só existem no Postgres (leg backend-postgres do CI)",
)


@so_no_postgres
def test_todo_enum_do_modelo_existe_inteiro_no_banco():
    from sqlalchemy import text
    from sqlmodel import SQLModel

    import app.models  # noqa: F401  (popula a metadata)

    # Os enums declarados nas colunas do modelo, por nome do TIPO no banco.
    esperado: dict[str, set[str]] = {}
    for tabela in SQLModel.metadata.tables.values():
        for coluna in tabela.columns:
            tipo = getattr(coluna.type, "enums", None)
            nome = getattr(coluna.type, "name", None)
            if tipo and nome:
                esperado.setdefault(nome.lower(), set()).update(tipo)

    assert esperado, "nenhum enum encontrado na metadata — a varredura quebrou"

    with Session(engine) as session:
        linhas = session.exec(
            text(
                "SELECT t.typname, e.enumlabel "
                "FROM pg_type t JOIN pg_enum e ON t.oid = e.enumtypid"
            )
        ).all()

    no_banco: dict[str, set[str]] = {}
    for typname, label in linhas:
        no_banco.setdefault(typname.lower(), set()).add(label)

    divergencias = []
    for nome, valores in esperado.items():
        if nome not in no_banco:
            continue  # tipo ainda não criado neste banco — outro teste cobre
        faltando = valores - no_banco[nome]
        if faltando:
            divergencias.append(
                f"{nome}: o modelo tem {sorted(faltando)} que o banco não aceita — "
                f"falta uma migração com ALTER TYPE ... ADD VALUE"
            )

    assert not divergencias, "\n".join(divergencias)
