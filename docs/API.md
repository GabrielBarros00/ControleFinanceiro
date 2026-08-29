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

Em `/debts`, `/debts/monthly` e `/debts/by-month` o recorte acontece na **saída**: o ledger é calculado inteiro (o pareamento de dívidas precisa de todos os saldos para dar o valor certo) e depois filtrado nas linhas que envolvem você — com `totals` acompanhando o que ficou listado. Os pares em `/me/*` (`/me/debts`, `/me/debts/monthly`, `/me/debts/by-month`, `/me/settlements`) aplicam esse recorte **sempre**, mesmo para admin/owner: lá o escopo é a pessoa, não a casa (ADR 0027).

Em `/debts/by-month` o recorte vale para `net_debts` de cada mês, **não** para `balance`: o saldo é o seu por inteiro, e recortá-lo devolveria um total diferente do que `/debts` mostra na mesma tela.

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

- **20 requisições/min por IP + rota** (`RATE_LIMIT_AUTH_PER_MINUTE`) — o balde geral. Generoso de propósito: um IP é COMPARTILHADO por todo mundo atrás do mesmo Wi-Fi, empresa ou CGNAT da operadora, e um teto apertado tranca gente legítima sem impedir ataque nenhum (quem ataca troca de IP);
- **10 tentativas/min por CONTA alvo** (`RATE_LIMIT_ACCOUNT_PER_MINUTE`, login e forgot-password) — é ele que barra força bruta contra um alvo, e o custo do ataque deixa de depender de quantos IPs o atacante consegue arranjar. Tem de continuar sendo o **menor** dos dois.

O balde por IP só vale se o cliente não puder escolher o próprio IP, e isso depende de duas configurações que andam juntas: o nginx **sobrescreve** `X-Forwarded-For` com `$remote_addr` (`frontend/nginx.conf`) e o uvicorn confia apenas na faixa da rede do Compose (`--forwarded-allow-ips`, no `backend/Dockerfile`). Com `'*'` e um `X-Forwarded-For` acrescentado em vez de sobrescrito, o uvicorn lê a entrada mais à esquerda da lista — o valor que o próprio cliente mandou — e trocá-lo a cada tentativa dava um balde novo. O smoke de produção verifica isso (`X-Forwarded-For forjado nao escapa do rate limit`).

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
| **Pessoal — o mês** | `/me/overview`, `/me/activity`, `/me/report-currency` | O mês da PESSOA somando todos os workspaces (ADR 0020). Devolve **consumo** (minha parte), **saída de caixa** (o que saiu do meu bolso), **a pagar/receber** (por workspace, nunca compensados entre eles) e **resultado** (renda − consumo) |
| **Pessoal — compromissos** | `/me/commitments` | Faturas e financiamentos, **separados por prazo**: `overdue`, `due_this_month`, `next_installments`, `outstanding_total`, `monthly_commitment`. O `total` único de antes somava a próxima fatura com o principal inteiro dos financiamentos |
| **Pessoal — contas a pagar** | `/me/payables` | O que ainda NÃO saiu do caixa: lançamento fora do cartão sem `settled_at` (ADR 0029). Filtros `month`, `workspace_id`, `include_overdue`. Eixo diferente de `/me/commitments` — ali é a instituição (fatura, financiamento), aqui é a conta do mês |
| **Pessoal — renda** | `/me/income`, `/me/recurring-income` | `GET` (filtro `month=YYYY-MM`, por competência), `POST/PUT/DELETE`; `POST /recurring-income/generate`. Moeda default = `User.report_currency` |
| **Pessoal — cartões** | `/me/credit-cards` | CRUD (o `DELETE` devolve `409` se houver fatura em aberto — senão a dívida ficaria sem tela por onde ser quitada); `GET /{id}/statement-for?on=YYYY-MM-DD[&shift=N]` (em qual fatura cairia uma compra nessa data — só leitura; devolve `days_to_closing` e `options`, as faturas vizinhas alcançáveis com o `shift` de cada, ADR 0032); `GET /{id}/statements`; `POST /{id}/statements/{sid}/close\|pay\|reopen` |
| **Pessoal — contas** | `/me/payment-accounts` | `GET/POST/PUT/DELETE`. Nome único por DONO |
| **Pessoal — acertos** | `/me/debts`, `/me/settlements` | Com quem eu me acerto somando TODAS as casas (ADR 0027). `GET /debts` (saldo por casa, `by_workspace` + `excluded_workspaces`), `GET /debts/monthly?month=YYYY-MM` (uma seção por casa, mesmo payload de `/{ws}/debts/monthly` + `people`), `GET /debts/by-month` (a origem do saldo, uma seção por casa, sem total agregado), `GET /settlements?limit=&offset=` (histórico). **Só leitura**, e sempre `involved_only`: acerto entre terceiros não aparece nem para admin. Nada é compensado entre casas |
| **Pessoal — financiamentos** | `/me/financing` | CRUD; `GET /{id}/schedule`; `POST /{id}/early-settlement`; `POST /{id}/installments/{n}/pay\|unpay` (o `pay` aceita `workspace_id` opcional: informado, lança também a despesa lá) |
| **Notificações** | `/notifications` | `GET` (as suas + contagem de não lidas), `POST /{id}/read`, `POST /read-all` — escopo PESSOAL, sem `require_role` |
| **Transações** | `/{ws}/transactions` | `GET` (filtros: mês, busca, categoria, método, tag, `settled`), `POST`, `PUT`, `DELETE` (os dois aceitam `settled`: "já foi paga", ADR 0029); `POST /preview` (dry-run da divisão); `POST /bulk`; compra parcelada: `GET/PUT/DELETE /{id}/installment-group` (editar/excluir o grupo inteiro) + `POST /{id}/installment-group/cancel` |
| **Contas a pagar (espaço)** | `/{ws}/payables` | `GET` (o que esta casa tem em aberto, recortado pelo acesso financeiro); `POST /settle` (`{transaction_ids, settled, settled_on}`) — a única porta que move dinheiro para o caixa sem editar o lançamento, e que por isso **não** toca em `status` |
| **Anexos** | `/{ws}/transactions/{id}/attachments`, `/{ws}/attachments/{id}` | upload (magic bytes + hash), listar, download, excluir. O conteúdo fica fora do banco (ADR 0007); `404` no download significa objeto ausente no armazenamento, não anexo inexistente |
| **Categorias** | `/{ws}/categories` | `GET/POST/PUT/DELETE` |
| **Tags** | `/{ws}/tags` | `GET/POST/PUT/DELETE` (nome reativável) |
| **Dívidas** | `/{ws}/debts` | `GET` (saldo líquido consolidado); `GET /monthly?month=YYYY-MM` (retrato do mês por `billing_month`); `GET /by-month` (de quais meses vem o saldo acumulado de quem pediu). **Desta casa**, incluindo dívida entre TERCEIROS para quem tem acesso completo |
| **Acertos** | `/{ws}/settlements` | `GET/POST/DELETE` (validado contra a dívida). Único caminho de ESCRITA — a tela global manda o `workspace_id` da linha |
| **Recorrências (despesa)** | `/{ws}/recurring` | CRUD + geração/materialização de instâncias. `POST /{id}/preview` devolve, **sem escrever nada**, o que acontece com cada lançamento (`move`/`update`/`cancel`/`create`/`none`); o `PUT` aplica os escolhidos via `?apply_to=&create_occurrence=&since=` e o `DELETE` cancela os escolhidos via `?cancel_instance=` (ADR 0030). `?scope=none\|future\|all` segue valendo para quem chama sem revisão — e ali a data continua congelada. `end_date` (ou `end_after_occurrences`, convertido no servidor) dá fim à série |
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
