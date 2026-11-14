# ADR 0043 — PostgreSQL usa Psycopg 3 explicitamente, com sessões síncronas

**Status:** aceito (2026-11-14)
**Relacionados:** ADR 0010 (transações), ADR 0025 (datas).

## Contexto

O SQLAlchemy 2.1 mudou o driver padrão de `postgresql://` de psycopg2 para
Psycopg 3. O PR #198 subia o ORM e mantinha somente psycopg2 instalado:
as migrações e o stack real paravam com `No module named psycopg`.
O app usa SQLModel/SQLAlchemy, sem API direta de psycopg2. O driver pode ser
atualizado mantendo a arquitetura síncrona e a política de um worker.

## Decisão

- Instalar `psycopg[binary]` com versão fixa, removendo psycopg2. O extra inclui
  a extensão compilada e libpq, sem compiladores na imagem de produção.
- Usar `postgresql+psycopg://` explicitamente, inclusive em Compose e CI.
  Settings normaliza as URLs antigas `postgresql://`, `postgres://` e
  `postgresql+psycopg2://` para manter os ambientes existentes compatíveis.
  Credenciais codificadas e parâmetros são preservados sem reinterpretação.
- Manter `create_engine`, `Session`, pool do SQLAlchemy, transações e um
  worker. Rotas síncronas seguem no pool de threads do FastAPI; trechos async
  continuam encaminhando o acesso ao banco ao pool de threads.
- Validar o driver primeiro em Python 3.14/SQLAlchemy 2.0; a atualização do
  ORM e a de Python são etapas posteriores com CI completo próprio.

## Consequências

Não há mudança de schema nem cópia/conversão de dados. Alembic e os comandos
REST/MCP usam a mesma configuração. Decimal, precisão dos itens, datas UTC
sem fuso, JSON e savepoints ganham testes de ida e volta no Postgres; a suíte
completa inclui as invariantes financeiras e de concorrência.
O ambiente de teste também normaliza TEST_DATABASE_URL para que os engines
das fixtures concorrentes usem o mesmo driver. SQLite segue inalterado.

As diferenças de adaptação de parâmetros, prepared statements e erros do
driver exigem validar Postgres real e o stack de produção. Trocar o driver
não autoriza alterar o ponto de commit das rotas nem desativar os gates.

Referências: [migração Psycopg](https://www.psycopg.org/psycopg3/docs/basic/from_pg2.html)
e [SQLAlchemy/Psycopg](https://docs.sqlalchemy.org/en/20/dialects/postgresql.html#module-sqlalchemy.dialects.postgresql.psycopg).
