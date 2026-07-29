# Arquitetura

Visão técnica do Controle Financeiro V4: camadas, modelo de dados, tempo real, autenticação, migrações e topologia de deploy. Decisões que valem uma justificativa própria estão em [ADRs](adr/README.md).

## Visão geral

```
                        ┌──────────────────────────────────────────┐
   navegador  ─────────▶│  nginx (container frontend, porta 80)     │
   (SPA React)          │  · serve o SPA compilado                  │
                        │  · faz proxy de /api/v1 e /api/v1/ws  ─────┼──▶ backend
                        └──────────────────────────────────────────┘     (uvicorn, 1 worker)
                                                                              │
                                                                              ▼
                                                                         PostgreSQL 16
```

Em **produção** só o container do frontend (nginx) é exposto ao host; backend e banco ficam na rede interna do Docker Compose. Em **dev**, Vite (5173) e uvicorn (8000) rodam direto, com SQLite.

## Backend — camadas

O backend é FastAPI + SQLModel, organizado em camadas com dependências apontando “para dentro”:

| Camada | Pasta | Responsabilidade | Regras |
|---|---|---|---|
| **Rotas** | `app/api/routes/` | HTTP: valida entrada (Pydantic), autoriza (`deps.require_role`), **comanda a transação** (único `commit`) | Não contém regra de negócio pesada |
| **Serviços** | `app/services/` | Regras de negócio: splits, dívidas, faturas, recorrência, financiamento, forecast, eventos | Usam `flush()`, **nunca `commit()`** (ADR 0010) |
| **Domínio** | `app/domain/` | Primitivas puras e sem I/O: `Money` (centavos), `dates.add_months`, `query_policy` (status/moeda) | Testável isoladamente |
| **Modelos** | `app/models/` | Entidades SQLModel = tabelas; listeners de auditoria e de carimbo de status | Fonte do schema (via Alembic) |
| **Core** | `app/core/` | Config, JWT, cookies, CSRF, rate limit, contexto de usuário, auditoria automática | Infra transversal |
| **WS** | `app/ws/` | WebSocket por workspace, `ConnectionManager` in-process | Requer **1 worker** |

**Regra da transação (ADR 0010):** serviços preparam o estado com `flush()`; a **rota** faz o único `commit`. Assim, criar uma despesa com pagadores + divisões + itens + ajustes é atômico — qualquer erro faz `rollback` e nada fica órfão. O cálculo da divisão tem uma fonte única, `transaction_service.compute_transaction_breakdown`, usada por criação, edição, importação, recorrência e pelo endpoint de `preview`.

## Modelo de dados

Entidades principais (`app/models/`) e seus vínculos:

```
User ──< WorkspaceMembership >── Workspace ──< WorkspaceInvite
 │                                   │
 ├──< RefreshSession                 ├──< Category            ├──< Tag
 └──< Notification                   ├──< PaymentAccount      ├──< Income
      (pessoal: quem recebe          ├──< CreditCard ──< CardStatement ──< StatementPayment
       um convite ainda não          ├──< RecurringExpense    ├──< RecurringIncome
       é membro do workspace)        ├──< Financing ──< AmortizationInstallment
                                     ├──< MonthlyEstimate
                                     ├──< Settlement
                                     ├──< ImportBatch ──< ImportRow
                                     ├──< AuditLog        ├──< SyncEvent
                                     └──< Transaction
                                            ├──< TransactionPayer      (quem pagou, quanto, de onde)
                                            ├──< TransactionSplit      (quem deve quanto)
                                            ├──< TransactionItem ──< TransactionItemShare
                                            ├──< TransactionAdjustment (desconto/frete/...)
                                            └──  Attachment            (metadados + sha256 + chave;
                                                                        conteúdo no volume — ADR 0007/0016)

ExchangeRate  (global, sem workspace: cotação moeda→BRL por dia, alimentada pelo backfill)
```

Invariantes de despesa: `soma(pagadores) == total`, `total == soma(itens) + soma(ajustes)`, e a divisão soma exatamente o total (em centavos). A fatura (`statement_id`) é **sempre derivada no servidor** a partir de cartão + data (ADR 0002); nunca vem do cliente.

Todas as entidades de conteúdo têm `workspace_id` (isolamento multi-tenant) e a maioria usa **soft delete** (`deleted_at`). A `Transaction` tem `occurrence_date` com unique `(recurring_expense_id, occurrence_date)` — a instância excluída deixa *tombstone* e não ressuscita (ADR 0012).

## Consultas financeiras — política única

Para não existir “duas definições de gasto do mês”, todas as agregações (dívidas, relatórios, forecast, total de fatura) passam por `app/domain/query_policy.py`:

- **Status**: só `confirmed`/`paid` entram no realizado; `pending` também no forecast; `draft`/`cancelled` nunca (ADR 0003).
- **Moeda**: cada workspace tem `base_currency`. Lançamento em outra moeda é **convertido na entrada**, pela taxa cruzada `(from→BRL)/(base→BRL)` da data — fonte única em `ExchangeRateStore.rate_between` (ADR 0015). O que ficou gravado em outra moeda (legado) segue fora das agregações, e a contagem é exibida ao usuário.
- **Valores em `Decimal`** ponta a ponta — nada de `float`.

## Autenticação e sessão

- **Access token** (JWT, ~30 min) e **refresh token** (JWT, ~7 dias) em **cookies HttpOnly** — o front nunca vê os tokens.
- **Refresh persistido** (`RefreshSession`, `jti` + `family_id`): cada refresh **rotaciona** o token; reapresentar um token já rotacionado é tratado como roubo e **revoga a família inteira**; logout revoga a sessão (ADR 0013).
- **Google OAuth** por vínculo de e-mail; **reset de senha** por token com fingerprint do hash (uso único).
- **RBAC**: `role_level` (viewer < member < admin < owner) via `deps.require_role`; o backend é sempre a autoridade, o frontend apenas esconde ações que dariam 403.
- **Hardening**: CSRF por `Origin`/`Referer`, rate limit em `/auth/*`, `TrustedHost`, CSP/`X-Frame-Options`/`Permissions-Policy`, `/docs` desligado em produção.

Erros saem sempre no envelope `{"error": {"code", "message", "details"}}` (ver [API](API.md)).

## Tempo real (WebSocket)

- Endpoint: `GET /api/v1/ws/workspaces/{id}` — autenticado pelo cookie no handshake (`4401` pede refresh, `4403` encerra).
- Cada mutação publica um evento na **mesma transação**; o workspace tem um `event_seq` monotônico e uma tabela `SyncEvent` (unique `ws+seq`). A entrega ao cliente é *after commit*, via `ConnectionManager` in-process.
- O cliente (`frontend/src/hooks/use-workspace-events.ts`) mapeia `tipo de evento → query keys` e invalida o cache do TanStack Query. Se detectar **lacuna de seq** (ou `hello` divergente ao reconectar), faz **resync total**.

> **Restrição crítica:** o gerenciador de conexões é in-process → o backend **deve** rodar com `uvicorn --workers 1`. Escalar horizontalmente exige um broker (ex.: Redis) no seam `app/ws/manager`.

## Migrações de schema

**Alembic é o único caminho de evolução de schema** (ADR 0005). Cadeia linear, um único *head*. Em dev, o startup roda `alembic upgrade head` por conveniência; em produção, o entrypoint do container roda o upgrade antes de servir. Não há `create_all` no fluxo do app (só nos testes). Migrações que adicionam colunas são idempotentes (o DDL do SQLite não é transacional).

## Deploy

`docker-compose.yml` define:

- **db** — `postgres:16-alpine`, volume `postgres_data`, healthcheck.
- **backend** — build de `./backend`, `APP_ENV=production`, exige `SECRET_KEY` e `POSTGRES_PASSWORD` (falha o boot se ausentes/fracos), healthcheck em `/api/v1/health`.
- **frontend** — build de `./frontend` (SPA + nginx), única porta exposta (`HTTP_PORT:80`).
- **pgadmin** — só no profile `dev` (`docker compose --profile dev up`).

Configuração completa em [SETUP.md](../SETUP.md).
