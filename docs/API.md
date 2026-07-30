# Referência da API

API REST versionada sob **`/api/v1`**. Esta página cobre as convenções; o contrato completo (parâmetros, corpos, respostas) está no **OpenAPI interativo**.

## Explorando o contrato

- **Swagger UI / ReDoc** (apenas fora de produção): `http://localhost:8000/docs` e `/redoc`. Em produção ficam desligados (SEC-006).
- **OpenAPI JSON**: `GET /api/v1/openapi.json` (dev).
- **Tipos TypeScript gerados**: `frontend/src/types/api.gen.ts` (via `npm run typegen`).

## Convenções

### Autenticação
Sessão em **cookies HttpOnly** (`access_token` + `refresh_token`) — definidos por `POST /auth/login`, `/auth/register`, callback do Google, e renovados por `POST /auth/refresh`. Não há header `Authorization`; o navegador envia os cookies automaticamente. `POST /auth/logout` revoga a sessão.

### Autorização — dois eixos (ADR 0018)

**Papel** diz o que você FAZ; **acesso financeiro** diz o que você VÊ. São independentes.

| Eixo | Valores | Onde vive |
|---|---|---|
| Papel (`WorkspaceRole`) | `viewer < member < admin < owner` | `deps.require_role` |
| Acesso (`FinancialAccess`) | `involved_only`, `full_workspace` | `domain/access_policy.py` |

- **Papel**: escrita exige `member`; ações administrativas (membros, convites, auditoria), `admin`+. Sem permissão → `403`.
- **Acesso**: com `involved_only`, cada leitura devolve só o que **envolve** você — criou, pagou, tem divisão direta, ou participa da divisão de um item. `admin` e `owner` têm acesso completo pelo cargo, independente do valor gravado.

Duas consequências que mudam o contrato das respostas:

1. **Registro invisível responde `404`, não `403`** — um `403` confirmaria que ele existe naquele id.
2. **Campo da casa suprimido vem `null`, nunca `0`.** Afeta `total_expenses`, `total_income`, `net_savings`, `categories` (em `/analytics/summary` e `/analytics/reports`), as barras de `monthly_history`, e praticamente toda a `/analytics/forecast` — que é projeção de caixa da casa e, sem acesso completo, devolve apenas `my_budget`. Os campos `my_*` **nunca** são suprimidos: são dados do próprio usuário. Clientes devem tratar `null` como "sem acesso" e não coagir para zero.

Em `/debts`, `/debts/monthly` e `/liabilities/overview` o recorte acontece na **saída**: o ledger é calculado inteiro (o pareamento de dívidas precisa de todos os saldos para dar o valor certo) e depois filtrado nas linhas que envolvem você — com `totals` acompanhando o que ficou listado.

### Escopo pessoal × workspace (ADR 0019)

Renda, cartão, conta de pagamento e financiamento pertencem à **pessoa**, não ao workspace.

- `Income.workspace_id` / `RecurringIncome.workspace_id` são **anuláveis**: `null` = renda
  pessoal (aparece em todos os workspaces do dono, cadastrada uma vez); preenchido = renda
  **da casa** daquele workspace. `IncomeCreate.scope` (`personal` | `workspace`) escolhe, e
  o default é `personal`.
- `shared_with_workspace_ids` diz a quais orçamentos uma renda pessoal **contribui**. Vazio
  = privada. A lista enviada é o **estado final** (revogar é a mesma chamada), e só aceita
  workspaces de que o usuário participa.
- Cartão, conta e financiamento usam `PUT /{recurso}/{id}/shares`. No cartão, cada vínculo
  tem `access`: `use` (lançar compras e ver o subtotal daqui) ou `full` (fatura inteira).
- `PATCH /me/report-currency` define a moeda dos números pessoais — o que não pertence a um
  workspace não tem moeda-base de onde herdar, e a visão global soma casas que podem ter
  bases diferentes (ADR 0006).

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
Endpoints sensíveis de auth (`/auth/login`, `/auth/register`, `/auth/forgot-password`, `/auth/reset-password`) têm **dois baldes**, e estourar qualquer um devolve `429`:

- **5 requisições/min por IP + rota** — o balde geral;
- **10 tentativas/min por CONTA alvo** (login e forgot-password) — o balde por IP sozinho é contornável: o uvicorn roda com `--forwarded-allow-ips`, então quem alcança o backend diretamente forja `X-Forwarded-For` e ganha um balde novo a cada valor inventado. Amarrado à conta, o custo do ataque deixa de depender de quantos IPs o atacante consegue simular.

### Datas e dinheiro
Datas em ISO-8601 (UTC). Valores monetários como **string decimal** (ex.: `"90.00"`), nunca float. Cada workspace tem uma `base_currency` (BRL por padrão, trocável em Configurações). Lançamento em moeda diferente dela é **convertido para a moeda-base na entrada** — PTAX oficial do dia para as majores contra o real (AUD/CAD/CHF/DKK/EUR/GBP/JPY/NOK/SEK/USD), senão taxa de mercado (referência); + **IOF 3,5%** em compra no cartão. Quando a base não é BRL, a taxa é a **cruzada** `(from→BRL)/(base→BRL)` e a fonte vira `market` (a PTAX só é oficial contra o real) — ver [ADR 0015](adr/0015-conversao-na-entrada-e-taxa-cruzada.md). O original fica guardado (`original_amount`, `original_currency`, `exchange_rate`, `iof_rate`, `rate_source` = `ptax`|`market`). Recorrência estrangeira re-converte a cada mês, com a taxa daquele dia. Taxas históricas ficam num store local (`GET /{ws}/analytics/exchange-rate` devolve `{rate, source}`; sem `to_currency`, o alvo é a moeda-base do workspace).

Todo campo de moeda é validado como **código ISO-4217 alfabético de 3 letras** e normalizado para caixa alta na borda: código fora do formato é `422` no corpo (`currency`) e `400` na query (`from_currency`/`to_currency`). Não é preciosismo — o código entra na URL da fonte de câmbio, e um código inventado seria persistido e sumiria de *todas* as agregações (que filtram `currency == base_currency`) sem nenhum aviso.

## Endpoints por recurso

Base: `/api/v1`. `{ws}` = `workspaces/{workspace_id}`.

| Recurso | Rota base | Métodos principais |
|---|---|---|
| **Auth** | `/auth` | `POST register`, `login`, `logout`, `refresh`, `change-password`, `forgot-password`, `reset-password`, `onboarding`; `GET me`, `google/login`, `google/callback`; `PATCH me` |
| **Workspaces** | `/workspaces` | `GET/POST/PUT/DELETE`; `GET /{id}/base-currency/preview?to=XXX` (dry-run da troca de moeda-base) |
| **Membros / convites** | `/{ws}/members`, `/{ws}/invites` | listar/alterar papel/remover; criar/revogar convite (e-mail e link); `POST /{ws}/leave` |
| **Convites (aceite)** | `/invites` | `GET /info/{token}`, `POST /accept/{token}`, `POST /decline/{token}` — fora do escopo de workspace: quem recebe ainda não é membro |
| **Pessoal (global)** | `/me/overview`, `/me/commitments`, `/me/activity`, `/me/report-currency` | O mês da PESSOA somando todos os workspaces (ADR 0020). Sem `workspace_id` no caminho: o gate é só a sessão, e cada consulta filtra por `user_id`. Devolve **consumo** (minha parte), **saída de caixa** (o que saiu do meu bolso), **a pagar/receber** (por workspace, nunca compensados entre eles) e **resultado** (renda − consumo) |
| **Notificações** | `/notifications` | `GET` (as suas + contagem de não lidas), `POST /{id}/read`, `POST /read-all` — escopo PESSOAL, sem `require_role` |
| **Transações** | `/{ws}/transactions` | `GET` (filtros: mês, busca, categoria, método, tag), `POST`, `PUT`, `DELETE`; `POST /preview` (dry-run da divisão); `POST /bulk`; compra parcelada: `GET/PUT/DELETE /{id}/installment-group` (editar/excluir o grupo inteiro) + `POST /{id}/installment-group/cancel` |
| **Anexos** | `/{ws}/transactions/{id}/attachments`, `/{ws}/attachments/{id}` | upload (magic bytes + hash), listar, download, excluir. O conteúdo fica fora do banco (ADR 0007); `404` no download significa objeto ausente no armazenamento, não anexo inexistente |
| **Contas/carteiras** | `/{ws}/payment-accounts` | `GET/POST/PUT/DELETE` |
| **Cartões e faturas** | `/{ws}/credit-cards` | CRUD do cartão (o `DELETE` devolve `409` se houver fatura em aberto — senão a dívida ficaria sem tela por onde ser quitada); `GET /{id}/statement-for?on=YYYY-MM-DD` (em qual fatura cairia uma compra nessa data — só leitura, não cria fatura); `POST /{id}/statements/{sid}/close\|pay\|reopen` |
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
- O socket entra na sala **antes** de o servidor ler o `seq` do `hello`: nenhum evento com `seq` maior é publicado para uma sala sem ele. Em troca, um evento pode chegar **antes** do `hello` (com `seq` ≤ o dele) — o cliente nunca regride o marco.
- O `hello` é marco de sincronismo, não garantia de dados: na **primeira** conexão com um workspace o cliente faz resync total, porque o cache veio por HTTP sem correlação com o `seq`.

Detalhes de projeto em [ARCHITECTURE.md](ARCHITECTURE.md).
