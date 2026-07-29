# Referência da API

API REST versionada sob **`/api/v1`**. Esta página cobre as convenções; o contrato completo (parâmetros, corpos, respostas) está no **OpenAPI interativo**.

## Explorando o contrato

- **Swagger UI / ReDoc** (apenas fora de produção): `http://localhost:8000/docs` e `/redoc`. Em produção ficam desligados (SEC-006).
- **OpenAPI JSON**: `GET /api/v1/openapi.json` (dev).
- **Tipos TypeScript gerados**: `frontend/src/types/api.gen.ts` (via `npm run typegen`).

## Convenções

### Autenticação
Sessão em **cookies HttpOnly** (`access_token` + `refresh_token`) — definidos por `POST /auth/login`, `/auth/register`, callback do Google, e renovados por `POST /auth/refresh`. Não há header `Authorization`; o navegador envia os cookies automaticamente. `POST /auth/logout` revoga a sessão.

### Autorização (RBAC)
Rotas de workspace exigem papel mínimo: `viewer < member < admin < owner`. Leitura costuma exigir `viewer`/membro; escrita, `member`; ações administrativas (membros, auditoria), `admin`+. Sem permissão → `403`.

### Envelope de erro
**Toda** resposta de erro (401/403/404/409/422/500) usa:
```json
{ "error": { "code": "STRING", "message": "mensagem em PT-BR", "details": {} } }
```
No frontend: leia `err.response?.data?.error?.message`. Erros estruturais de validação saem como `422`; violações de regra de negócio (somas, membership, transições) como `400`/`409` com mensagem clara.

### Paginação
Listagens paginadas (ex.: transações) aceitam `page` e `limit` e retornam:
```json
{ "items": [...], "total": 123, "total_amount": "4567.89", "page": 1, "limit": 10, "total_pages": 13 }
```
`total_amount` é a soma do **filtro inteiro**, não da página devolvida — a tela a mostra ao
lado da contagem, e as duas precisam falar da mesma amostra.

### Rate limiting
Endpoints sensíveis de auth (`/auth/login`, `/auth/register`, `/auth/forgot-password`) têm limite de **5 requisições/min por IP** → `429` ao exceder.

### Datas e dinheiro
Datas em ISO-8601 (UTC). Valores monetários como **string decimal** (ex.: `"90.00"`), nunca float. Cada workspace tem uma `base_currency` (BRL por padrão, trocável em Configurações). Lançamento em moeda diferente dela é **convertido para a moeda-base na entrada** — PTAX oficial do dia para as majores contra o real (AUD/CAD/CHF/DKK/EUR/GBP/JPY/NOK/SEK/USD), senão taxa de mercado (referência); + **IOF 3,5%** em compra no cartão. Quando a base não é BRL, a taxa é a **cruzada** `(from→BRL)/(base→BRL)` e a fonte vira `market` (a PTAX só é oficial contra o real) — ver [ADR 0015](adr/0015-conversao-na-entrada-e-taxa-cruzada.md). O original fica guardado (`original_amount`, `original_currency`, `exchange_rate`, `iof_rate`, `rate_source` = `ptax`|`market`). Recorrência estrangeira re-converte a cada mês, com a taxa daquele dia. Taxas históricas ficam num store local (`GET /{ws}/analytics/exchange-rate` devolve `{rate, source}`; sem `to_currency`, o alvo é a moeda-base do workspace).

## Endpoints por recurso

Base: `/api/v1`. `{ws}` = `workspaces/{workspace_id}`.

| Recurso | Rota base | Métodos principais |
|---|---|---|
| **Auth** | `/auth` | `POST register`, `login`, `logout`, `refresh`, `change-password`, `forgot-password`, `reset-password`, `onboarding`; `GET me`, `google/login`, `google/callback`; `PATCH me` |
| **Workspaces** | `/workspaces` | `GET/POST/PUT/DELETE`; `GET /{id}/base-currency/preview?to=XXX` (dry-run da troca de moeda-base) |
| **Membros / convites** | `/{ws}/members`, `/{ws}/invites` | listar/alterar papel/remover; criar/revogar convite (e-mail e link); `POST /{ws}/leave` |
| **Convites (aceite)** | `/invites` | `GET /info/{token}`, `POST /accept/{token}`, `POST /decline/{token}` — fora do escopo de workspace: quem recebe ainda não é membro |
| **Notificações** | `/notifications` | `GET` (as suas + contagem de não lidas), `POST /{id}/read`, `POST /read-all` — escopo PESSOAL, sem `require_role` |
| **Transações** | `/{ws}/transactions` | `GET` (filtros: mês, busca, categoria, método, tag), `POST`, `PUT`, `DELETE`; `POST /preview` (dry-run da divisão); `POST /bulk`; compra parcelada: `GET/PUT/DELETE /{id}/installment-group` (editar/excluir o grupo inteiro) + `POST /{id}/installment-group/cancel` |
| **Anexos** | `/{ws}/transactions/{id}/attachments`, `/{ws}/attachments/{id}` | upload (magic bytes + hash), listar, download, excluir. O conteúdo fica fora do banco (ADR 0007); `404` no download significa objeto ausente no armazenamento, não anexo inexistente |
| **Contas/carteiras** | `/{ws}/payment-accounts` | `GET/POST/PUT/DELETE` |
| **Cartões e faturas** | `/{ws}/credit-cards` | CRUD do cartão; `POST /{id}/statements/{sid}/close\|pay\|reopen` |
| **Categorias** | `/{ws}/categories` | `GET/POST/PUT/DELETE` |
| **Tags** | `/{ws}/tags` | `GET/POST/PUT/DELETE` (nome reativável) |
| **Renda** | `/{ws}/income` | `GET` (filtro `month=YYYY-MM`, por competência), `POST/PUT/DELETE` |
| **Dívidas** | `/{ws}/debts` | `GET` (saldo líquido consolidado); `GET /monthly?month=YYYY-MM` (retrato do mês por `billing_month`) |
| **Acertos** | `/{ws}/settlements` | `GET/POST/DELETE` (validado contra a dívida) |
| **Recorrências (despesa)** | `/{ws}/recurring` | CRUD (`PUT` aceita `?scope=none\|future\|all`) + geração/materialização de instâncias |
| **Recorrências (renda)** | `/{ws}/recurring-income` | CRUD + `POST /generate` (materializa as rendas recorrentes do mês) |
| **Financiamentos** | `/{ws}/financing` | CRUD; `GET /{id}/schedule`; `POST /{id}/early-settlement`; `POST /{id}/installments/{n}/pay` |
| **Endividamento** | `/{ws}/liabilities` | `GET` (panorama consolidado: financiamentos + faturas de cartão em aberto) |
| **Importação CSV** | `/{ws}/imports` | `POST /parse` (mapeia colunas + marca duplicatas), `POST /commit` (decisão por linha, idempotente) |
| **Analytics** | `/{ws}/analytics` | `GET /summary`, `/reports`, `/forecast`, `/exchange-rate`; estimativas: `GET/POST/PUT/DELETE /estimates` |
| **Auditoria** | `/{ws}/audit` | `GET` (admin+; trilha por workspace) |
| **Health** | `/health` | `GET` → `{ "status": "ok", "version": "..." }` |

## WebSocket

- `GET /api/v1/ws/workspaces/{id}` — autenticado pelo cookie no handshake.
- Códigos de fechamento: `4401` (token expirado → o cliente renova e reconecta), `4403` (sem permissão → não reconecta).
- Mensagens: `hello` (com `seq` atual), eventos `{type, seq, ...}` e `ping/pong`. O cliente invalida as *query keys* correspondentes; lacuna de `seq` → resync total.

Detalhes de projeto em [ARCHITECTURE.md](ARCHITECTURE.md).
