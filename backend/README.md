# Backend — Controle Financeiro V4

API em **FastAPI + SQLModel**, com **Alembic** (migrações), **PostgreSQL** em produção e **SQLite** em dev. Parte do monorepo — veja o [README principal](../README.md), a [arquitetura](../docs/ARCHITECTURE.md) e a [API](../docs/API.md).

## Rodando em dev

```bash
python -m venv .venv && source .venv/bin/activate   # Windows: .venv\Scripts\activate
pip install -r requirements-dev.txt                  # puxa produção via requirements.in
cp .env.example .env                                 # SQLite local, defaults prontos
python -m uvicorn app.main:app --reload              # http://localhost:8000
```

Docs interativas (só fora de produção): <http://localhost:8000/docs>.

## Testes e lint

```bash
python -m pytest                     # SQLite em memória
ruff check app                      # lint (formatação NÃO: ver nota abaixo)

# contra Postgres (como no CI):
TEST_DATABASE_URL=postgresql+psycopg2://user:pass@localhost:5432/db APP_ENV=test python -m pytest
```

> **Não rode `ruff format`.** O backend nunca foi formatado com ele: hoje o
> `ruff format --check` reescreveria 297 dos 317 arquivos. Formatar em pedaços
> espalha ruído por commits que falam de outra coisa, então o CI não checa
> formato e o hook `ruff-format` está fora do pre-commit de propósito. Quando a
> decisão for tomada, é um commit isolado — e aí o hook volta e o check entra no
> CI na mesma mudança (`test_versao_de_plataforma.py` cobra os dois juntos).

## Estrutura (`app/`)

```
api/routes/   # rotas REST por recurso (validam, autorizam, comandam a transação)
api/deps.py   # dependências de autorização (require_role)
services/     # regras de negócio (usam flush(), nunca commit — ADR 0010)
domain/       # primitivas puras: Money (centavos), dates, query_policy
models/       # entidades SQLModel = tabelas (+ listeners de auditoria/status)
core/         # config, jwt, cookies, csrf, rate_limit, auditoria, contexto
ws/           # WebSocket por workspace (ConnectionManager in-process)
main.py       # app, middlewares (CSRF, headers, logging), lifespan
```

## Migrações

Alembic é o único caminho de schema (ADR 0005). Veja [CONTRIBUTING.md](../CONTRIBUTING.md#migrações-alembic) para o fluxo (`alembic revision` → `upgrade` idempotente → validar em SQLite e Postgres).

## Configuração

Todas as variáveis estão em `app/core/config.py` e documentadas em `.env.example`. Em `APP_ENV=production`, o boot é recusado com configuração insegura (SECRET_KEY fraca, `COOKIE_SECURE=False`, banco não-Postgres). Guia completo em [SETUP.md](../SETUP.md).

> **Restrição:** rode com **1 worker** (`uvicorn --workers 1`) — o gerenciador de WebSocket é in-process.
