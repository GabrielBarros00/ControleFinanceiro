# Guia de contribuição

Como configurar o ambiente, rodar as verificações e seguir as convenções do projeto.

## Ambiente de desenvolvimento

Pré-requisitos: **Python 3.12+**, **Node 20+**, e (opcional) **Docker** para rodar o stack completo ou testar contra Postgres.

```bash
# Backend
cd backend
python -m venv .venv && source .venv/bin/activate   # Windows: .venv\Scripts\activate
pip install -r requirements-dev.txt   # inclui produção + pytest/ruff
cp .env.example .env
python -m uvicorn app.main:app --reload             # http://localhost:8000

# Frontend
cd frontend
npm install
npm run dev                                         # http://localhost:5173
```

Em dev o banco é SQLite (`backend/dev.db`), criado/migrado no startup; links de e-mail saem no console.

## Verificações (rode antes de abrir PR)

Opcional, mas recomendado: `pip install pre-commit && pre-commit install` — os hooks de [`.pre-commit-config.yaml`](.pre-commit-config.yaml) rodam ruff (backend) e eslint (frontend) automaticamente a cada commit.

```bash
make test        # pytest + vitest
make lint        # ruff + eslint

# Backend
cd backend && python -m pytest              # SQLite em memória
cd backend && ruff check app && ruff format --check app

# Frontend
cd frontend && npm test                     # vitest
cd frontend && npm run lint                 # eslint
cd frontend && npm run build                # tsc + vite build
cd frontend && npm run test:e2e             # Playwright (sobe backend+frontend)
```

### Rodar a suíte contra PostgreSQL

O CI e a validação de produção usam Postgres. Para reproduzir localmente:

```bash
docker run -d --rm --name cf_pg -e POSTGRES_PASSWORD=dev -p 5432:5432 postgres:16
# aguarde o banco aceitar conexões, então:
TEST_DATABASE_URL=postgresql+psycopg2://postgres:dev@localhost:5432/postgres \
  APP_ENV=test python -m pytest
```

> Os testes montam o schema via `create_all` a partir dos **models**, que podem declarar FKs que as migrações não criam. Por isso a suíte pode passar em SQLite (que não impõe FK) e falhar em Postgres — **sempre valide migrações/mudanças de model contra Postgres**.

## Migrações (Alembic)

Alembic é o **único** caminho de schema (ADR 0005). Ao mudar um model:

```bash
cd backend
alembic revision -m "descrição curta"       # crie a revisão
# edite o arquivo em alembic/versions/: escreva upgrade()/downgrade() IDEMPOTENTES
alembic upgrade head                         # aplique em dev
```

- Mantenha a cadeia **linear** (um único *head*): `down_revision` aponta para o head anterior.
- `upgrade()` deve ser idempotente (checar `inspector` antes de `add_column`/`create_table`) — o DDL do SQLite não é transacional.
- Valide o upgrade **do zero** e contra uma **cópia** do banco, em SQLite e Postgres.

## Tipos gerados do OpenAPI

```bash
cd frontend && npm run typegen   # dump do OpenAPI + openapi-typescript → src/types/api.gen.ts
```
Zod é usado só para UX de formulário; o contrato de dados vem do backend.

## Convenções

- **Commits**: mensagens no estilo convencional (`feat:`, `fix:`, `docs:`, `chore:`, `test:`), imperativo, em PT-BR. Uma mudança coesa por commit.
- **Erros**: sempre no envelope `{"error": {...}}` (ver [docs/API.md](docs/API.md)); mensagens de negócio em PT-BR.
- **Transações**: serviços usam `flush()`, a rota faz o `commit` (ADR 0010). Não commite dentro de um serviço.
- **Dinheiro**: `Decimal`/centavos, nunca `float`. Use `app/domain/money.py`.
- **Decisões**: mudanças arquiteturais relevantes viram um ADR em [docs/adr/](docs/adr/README.md).
- **WebSocket**: o backend roda com **1 worker** (gerenciador in-process); não altere isso sem introduzir um broker.
