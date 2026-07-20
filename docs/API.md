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
{ "items": [...], "total": 123, "page": 1, "limit": 10, "total_pages": 13 }
```

### Rate limiting
Endpoints sensíveis de auth (`/auth/login`, `/auth/register`, `/auth/forgot-password`) têm limite de **5 requisições/min por IP** → `429` ao exceder.

### Datas e dinheiro
Datas em ISO-8601 (UTC). Valores monetários como **string decimal** (ex.: `"90.00"`), nunca float. Cada workspace tem uma `base_currency`; valores em outra moeda não entram nas agregações.

## Endpoints por recurso

Base: `/api/v1`. `{ws}` = `workspaces/{workspace_id}`.

| Recurso | Rota base | Métodos principais |
|---|---|---|
| **Auth** | `/auth` | `POST register`, `login`, `logout`, `refresh`, `change-password`, `forgot-password`, `reset-password`, `onboarding`; `GET me`, `google/login`, `google/callback`; `PATCH me` |
| **Workspaces** | `/workspaces` | `GET/POST/PUT/DELETE` |
| **Membros / convites** | `/{ws}/members`, `/{ws}/invites` | listar/alterar papel/remover; criar/aceitar/revogar convite (e-mail e link) |
| **Transações** | `/{ws}/transactions` | `GET` (filtros: mês, busca, categoria, método, tag), `POST`, `PUT`, `DELETE`; `POST /preview` (dry-run da divisão); `POST /bulk`; grupo de parcelas: `POST/DELETE /{id}/installment-group[/cancel]` |
| **Anexos** | `/{ws}/transactions/{id}/attachments`, `/{ws}/attachments/{id}` | upload (magic bytes + hash), listar, download, excluir |
| **Contas/carteiras** | `/{ws}/payment-accounts` | `GET/POST/PUT/DELETE` |
| **Cartões e faturas** | `/{ws}/credit-cards` | CRUD do cartão; `POST /{id}/statements/{sid}/close\|pay\|reopen` |
| **Categorias** | `/{ws}/categories` | `GET/POST/PUT/DELETE` |
| **Tags** | `/{ws}/tags` | `GET/POST/PUT/DELETE` (nome reativável) |
| **Renda** | `/{ws}/income` | `GET/POST/PUT/DELETE` |
| **Dívidas** | `/{ws}/debts` | `GET` (saldo líquido consolidado) |
| **Acertos** | `/{ws}/settlements` | `GET/POST/DELETE` (validado contra a dívida) |
| **Recorrências** | `/{ws}/recurring` | CRUD + geração/materialização de instâncias |
| **Financiamentos** | `/{ws}/financing` | CRUD; `GET /{id}/schedule`; `POST /{id}/early-settlement`; `POST /{id}/installments/{n}/pay` |
| **Importação CSV** | `/{ws}/imports` | `POST /parse` (mapeia colunas + marca duplicatas), `POST /commit` (decisão por linha, idempotente) |
| **Analytics** | `/{ws}/analytics` | `GET /summary`, `/reports`, `/forecast`, `/exchange-rate`; estimativas: `GET/POST/PUT/DELETE /estimates` |
| **Auditoria** | `/{ws}/audit` | `GET` (admin+; trilha por workspace) |
| **Health** | `/health` | `GET` → `{ "status": "ok", "version": "..." }` |

## WebSocket

- `GET /api/v1/ws/workspaces/{id}` — autenticado pelo cookie no handshake.
- Códigos de fechamento: `4401` (token expirado → o cliente renova e reconecta), `4403` (sem permissão → não reconecta).
- Mensagens: `hello` (com `seq` atual), eventos `{type, seq, ...}` e `ping/pong`. O cliente invalida as *query keys* correspondentes; lacuna de `seq` → resync total.

Detalhes de projeto em [ARCHITECTURE.md](ARCHITECTURE.md).
