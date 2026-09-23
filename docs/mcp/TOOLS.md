# Tools do servidor MCP

<!-- GERADO por `python -m app.mcp.docs` a partir de `backend/app/mcp/registry.py`. Não edite à mão. -->

Servidor `controle-financeiro` versão `1.2.0` · 38 tools · endpoint `/mcp` (Streamable HTTP).

Convenções que valem para todas: dinheiro em string decimal com ponto (`"89.90"`, até 2 casas, nunca arredondado); datas `YYYY-MM-DD` e meses `YYYY-MM` no fuso da conta (`profile_get.timezone`); nomes resolvidos no servidor (ambíguo → `AMBIGUOUS` com candidatos); nenhuma tool aceita `user_id` — a identidade vem do token.

## Escopos

| Escopo | Para quê | Obrigatório |
|---|---|---|
| `finance.read` | Lançamentos, faturas, contas, saldos, rendas, dívidas e relatórios — o mesmo que você vê no app. | sim |
| `transactions.write` | Criar, editar, categorizar, marcar como pago, excluir e importar lançamentos (com parcelas e divisões). | não |
| `accounts.write` | Pagar fatura, transferir entre suas contas e ajustar saldo. | não |
| `income.write` | Lançar rendas e marcar como recebidas ou canceladas. | não |
| `settlements.write` | Registrar e desfazer pagamentos de dívidas entre membros de um espaço. | não |
| `planning.write` | Criar e editar recorrências, orçamentos e categorias. | não |

## Códigos de erro

Toda falha volta com `isError: true` e `{"error": {code, message, details, retryable}}`.

`NOT_FOUND`, `AMBIGUOUS`, `VALIDATION_ERROR`, `AUTHENTICATION_REQUIRED`, `PERMISSION_DENIED`, `CONFLICT`, `RATE_LIMITED`, `ALREADY_EXISTS`, `BUSINESS_RULE_VIOLATION`, `INTERNAL_ERROR`

## Índice

| Tool | Título | Classe | Escopo |
|---|---|---|---|
| [`profile_get`](#profile_get--conta-conectada) | Conta conectada | Leitura | `finance.read` |
| [`spaces_list`](#spaces_list--listar-espaços) | Listar espaços | Leitura | `finance.read` |
| [`people_list`](#people_list--listar-pessoas) | Listar pessoas | Leitura | `finance.read` |
| [`categories_list`](#categories_list--listar-categorias-e-tags) | Listar categorias e tags | Leitura | `finance.read` |
| [`cards_list`](#cards_list--listar-cartões) | Listar cartões | Leitura | `finance.read` |
| [`accounts_list`](#accounts_list--contas-e-saldo) | Contas e saldo | Leitura | `finance.read` |
| [`transactions_search`](#transactions_search--buscar-lançamentos) | Buscar lançamentos | Leitura | `finance.read` |
| [`transactions_get`](#transactions_get--ver-lançamento) | Ver lançamento | Leitura | `finance.read` |
| [`transactions_show`](#transactions_show--mostrar-lançamento-na-conversa) | Mostrar lançamento na conversa | Leitura | `finance.read` |
| [`statements_get`](#statements_get--ver-fatura-do-cartão) | Ver fatura do cartão | Leitura | `finance.read` |
| [`statements_show`](#statements_show--mostrar-fatura-na-conversa) | Mostrar fatura na conversa | Leitura | `finance.read` |
| [`reports_summary`](#reports_summary--resumo-financeiro-do-mês) | Resumo financeiro do mês | Leitura | `finance.read` |
| [`reports_show`](#reports_show--mostrar-resumo-do-mês-na-conversa) | Mostrar resumo do mês na conversa | Leitura | `finance.read` |
| [`budgets_list`](#budgets_list--orçamentos-do-mês) | Orçamentos do mês | Leitura | `finance.read` |
| [`debts_summary`](#debts_summary--quem-deve-a-quem) | Quem deve a quem | Leitura | `finance.read` |
| [`payables_list`](#payables_list--contas-a-pagar) | Contas a pagar | Leitura | `finance.read` |
| [`income_list`](#income_list--rendas-do-mês) | Rendas do mês | Leitura | `finance.read` |
| [`recurring_list`](#recurring_list--despesas-e-rendas-recorrentes) | Despesas e rendas recorrentes | Leitura | `finance.read` |
| [`transactions_create`](#transactions_create--registrar-despesa) | Registrar despesa | Escrita | `transactions.write` |
| [`transactions_update`](#transactions_update--editar-lançamento) | Editar lançamento | Escrita | `transactions.write` |
| [`transactions_delete`](#transactions_delete--excluir-lançamento) | Excluir lançamento | Destrutiva | `transactions.write` |
| [`transactions_restore`](#transactions_restore--restaurar-lançamento-excluído) | Restaurar lançamento excluído | Escrita | `transactions.write` |
| [`transactions_bulk_preview`](#transactions_bulk_preview--prévia-de-ação-em-massa) | Prévia de ação em massa | Leitura | `finance.read` |
| [`transactions_bulk_delete`](#transactions_bulk_delete--excluir-em-massa-confirmado) | Excluir em massa (confirmado) | Destrutiva | `transactions.write` |
| [`transactions_bulk_categorize`](#transactions_bulk_categorize--categorizar-em-massa-confirmado) | Categorizar em massa (confirmado) | Escrita | `transactions.write` |
| [`imports_preview`](#imports_preview--conferir-linhas-de-extrato) | Conferir linhas de extrato | Leitura | `finance.read` |
| [`imports_commit`](#imports_commit--importar-linhas-de-extrato) | Importar linhas de extrato | Escrita | `transactions.write` |
| [`statements_pay`](#statements_pay--pagar-fatura-do-cartão) | Pagar fatura do cartão | Escrita | `accounts.write` |
| [`transfers_create`](#transfers_create--transferir-entre-contas) | Transferir entre contas | Escrita | `accounts.write` |
| [`accounts_adjust_balance`](#accounts_adjust_balance--conciliar-saldo-da-conta) | Conciliar saldo da conta | Escrita | `accounts.write` |
| [`income_create`](#income_create--registrar-renda) | Registrar renda | Escrita | `income.write` |
| [`income_update`](#income_update--atualizar-renda) | Atualizar renda | Escrita | `income.write` |
| [`settlements_create`](#settlements_create--registrar-acerto-entre-pessoas) | Registrar acerto entre pessoas | Escrita | `settlements.write` |
| [`settlements_delete`](#settlements_delete--desfazer-acerto) | Desfazer acerto | Destrutiva | `settlements.write` |
| [`recurring_create`](#recurring_create--criar-despesa-recorrente) | Criar despesa recorrente | Escrita | `planning.write` |
| [`recurring_update`](#recurring_update--editar-despesa-recorrente) | Editar despesa recorrente | Escrita | `planning.write` |
| [`budgets_set`](#budgets_set--definir-meta-do-mês) | Definir meta do mês | Escrita | `planning.write` |
| [`categories_create`](#categories_create--criar-categoria) | Criar categoria | Escrita | `planning.write` |

## Referência

### `profile_get` — Conta conectada

- **Classe:** Leitura · **Escopo:** `finance.read` · **Custo:** 1 unidade(s)
- **Annotations:** readOnlyHint=true, destructiveHint=false, idempotentHint=true, openWorldHint=false

Mostra qual conta do Controle Financeiro está conectada, as permissões desta conexão, o fuso horário e a data de HOJE da conta.

Use quando: no início da conversa, para saber a data de hoje antes de interpretar 'hoje/ontem/este mês', ou quando o usuário perguntar qual conta está conectada.

Não use quando: precisar de dados financeiros — use as tools de consulta.

**Entrada**

_Sem parâmetros._

**Saída (`structuredContent`)**: `id`, `name`, `email`, `nickname`, `environment`, `timezone`, `today`, `report_currency`, `app_url`, `connection`

### `spaces_list` — Listar espaços

- **Classe:** Leitura · **Escopo:** `finance.read` · **Custo:** 1 unidade(s)
- **Annotations:** readOnlyHint=true, destructiveHint=false, idempotentHint=true, openWorldHint=false

Lista os espaços (grupos financeiros: pessoal, casa, viagem…) de que você participa, com moeda-base, seu papel e quantos membros há.

Use quando: precisar escolher/confirmar em qual espaço registrar algo, ou o usuário perguntar em quais espaços participa.

Não use quando: quiser as pessoas de um espaço (people_list) ou valores (reports_summary).

**Entrada**

_Sem parâmetros._

**Saída (`structuredContent`)**: `spaces`

### `people_list` — Listar pessoas

- **Classe:** Leitura · **Escopo:** `finance.read` · **Custo:** 1 unidade(s)
- **Annotations:** readOnlyHint=true, destructiveHint=false, idempotentHint=true, openWorldHint=false

Lista as pessoas (membros) dos seus espaços, com o papel de cada uma. Só membros de um espaço podem entrar numa divisão de despesa.

Use quando: o usuário citar alguém ('divide com o João') e for preciso confirmar quem é ou resolver um nome ambíguo; ou perguntar quem participa de um espaço.

Não use quando: quiser saber quanto alguém deve (debts_summary).

**Entrada**

| Parâmetro | Tipo | Obrigatório | Descrição |
|---|---|---|---|
| `space` | string | não | Nome do espaço (opcional). (máx. 120) |
| `space_id` | integer | não | ID do espaço (opcional). |
| `query` | string | não | Filtra pelo nome da pessoa. (mín. 1, máx. 80) |

**Saída (`structuredContent`)**: `people`

### `categories_list` — Listar categorias e tags

- **Classe:** Leitura · **Escopo:** `finance.read` · **Custo:** 1 unidade(s)
- **Annotations:** readOnlyHint=true, destructiveHint=false, idempotentHint=true, openWorldHint=false

Lista as categorias e as tags de um espaço (cada espaço tem as suas).

Use quando: precisar escolher a categoria de um lançamento, resolver um nome de categoria ambíguo ou o usuário perguntar quais categorias existem.

Não use quando: quiser o gasto por categoria (reports_summary).

**Entrada**

| Parâmetro | Tipo | Obrigatório | Descrição |
|---|---|---|---|
| `space` | string | não | Nome do espaço. Omitido: seu único espaço. (máx. 120) |
| `space_id` | integer | não |  |

**Saída (`structuredContent`)**: `space`, `categories`, `tags`

### `cards_list` — Listar cartões

- **Classe:** Leitura · **Escopo:** `finance.read` · **Custo:** 1 unidade(s)
- **Annotations:** readOnlyHint=true, destructiveHint=false, idempotentHint=true, openWorldHint=false

Lista seus cartões de crédito com limite disponível, dia de fechamento/vencimento, a fatura do ciclo atual e a fatura em aberto mais urgente.

Use quando: o usuário perguntar sobre cartões/limite, ou for preciso achar o ID de um cartão citado por nome ambíguo.

Não use quando: quiser as compras de uma fatura (statements_get).

**Entrada**

_Sem parâmetros._

**Saída (`structuredContent`)**: `cards`

### `accounts_list` — Contas e saldo

- **Classe:** Leitura · **Escopo:** `finance.read` · **Custo:** 1 unidade(s)
- **Annotations:** readOnlyHint=true, destructiveHint=false, idempotentHint=true, openWorldHint=false

Lista suas contas (corrente, poupança, carteira…) com o saldo atual de cada uma, o total e o saldo PREVISTO para o fim do mês (a receber − a pagar).

Use quando: o usuário perguntar 'qual meu saldo', 'quanto vou ter no fim do mês', ou for preciso achar o ID de uma conta.

Não use quando: quiser gastos do mês (reports_summary) ou contas a pagar em detalhe (payables_list).

**Entrada**

_Sem parâmetros._

**Saída (`structuredContent`)**: `currency`, `total`, `accounts`, `month`, `projected_balance`, `receivable_total`, `payable_total`, `overdue_total`, `projection`

### `transactions_search` — Buscar lançamentos

- **Classe:** Leitura · **Escopo:** `finance.read` · **Custo:** 2 unidade(s)
- **Annotations:** readOnlyHint=true, destructiveHint=false, idempotentHint=true, openWorldHint=false

Busca lançamentos (despesas) em todos os seus espaços por período, texto, cartão, conta, categoria, tag, pessoa, valor, forma de pagamento e situação. Devolve a lista paginada (com `id`), o total do filtro inteiro e a SUA parte.

Use quando: precisar achar um lançamento para ver, editar ou excluir ('a compra do McDonald's de ontem'), ou responder 'quanto gastei com X' por período ou filtro.

Não use quando: quiser o resumo do mês por categoria (reports_summary) ou a fatura de um cartão (statements_get). Datas: YYYY-MM-DD; `month` filtra por competência.

**Entrada**

| Parâmetro | Tipo | Obrigatório | Descrição |
|---|---|---|---|
| `space` | string | não | Restringe a um espaço (nome). (máx. 120) |
| `space_id` | integer | não |  |
| `text` | string | não | Trecho do título ou da descrição. (mín. 1, máx. 80) |
| `date_from` | data `YYYY-MM-DD` | não | Data da compra a partir de (inclusive). |
| `date_to` | data `YYYY-MM-DD` | não | Data da compra até (inclusive). |
| `month` | string | não | Competência (mês do gasto), YYYY-MM. (padrão `^\d{4}-(0[1-9]|1[0-2])$`) |
| `card` | string | não | Nome do cartão de crédito. (máx. 120) |
| `card_id` | integer | não |  |
| `account` | string | não | Conta de onde saiu o dinheiro. (máx. 120) |
| `account_id` | integer | não |  |
| `category` | string | não | máx. 120 |
| `category_id` | integer | não |  |
| `uncategorized` | boolean | não | Só lançamentos sem categoria. |
| `tag` | string | não | máx. 60 |
| `person` | string | não | Pessoa envolvida (pagou ou divide). (máx. 120) |
| `person_id` | integer | não |  |
| `payment_method` | `credit_card` \| `debit_card` \| `pix` \| `cash` \| `bank_transfer` \| `boleto` \| `other` | não |  |
| `status` | lista de `draft` \| `pending` \| `confirmed` \| `paid` \| `cancelled` | não | máx. 5 |
| `settled` | boolean | não | true = já pago; false = a pagar (fora do cartão). |
| `min_amount` | string | não | Valor em string decimal com ponto e até 2 casas, ex.: "89.90". (padrão `^\d{1,16}([.,]\d{1,2})?$`) |
| `max_amount` | string | não | Valor em string decimal com ponto e até 2 casas, ex.: "89.90". (padrão `^\d{1,16}([.,]\d{1,2})?$`) |
| `installment_group_id` | string | não | Parcelas de uma mesma compra. (máx. 64) |
| `sort` | `date_desc` \| `date_asc` \| `amount_desc` \| `amount_asc` | não |  |
| `limit` | integer | não | ≥ 1, ≤ 50 |
| `cursor` | string | não | `next_cursor` da página anterior. (máx. 512) |

**Saída (`structuredContent`)**: `items`, `total_count`, `totals`, `my_share_totals`, `next_cursor`, `resolved`

### `transactions_get` — Ver lançamento

- **Classe:** Leitura · **Escopo:** `finance.read` · **Custo:** 1 unidade(s)
- **Annotations:** readOnlyHint=true, destructiveHint=false, idempotentHint=true, openWorldHint=false

Devolve um lançamento completo pelo `transaction_id`: valor, data, espaço, quem pagou, como foi dividido (a parte de cada pessoa), categoria, tags, cartão/fatura, parcelas e moeda original. Só dados; para DESENHAR o lançamento na conversa, use transactions_show.

Use quando: já tiver o id (de transactions_search ou de uma criação) e precisar dos detalhes antes de explicar ou editar.

Não use quando: ainda não souber o id (busque com transactions_search), ou o usuário pedir para ver/mostrar o lançamento (transactions_show).

**Entrada**

| Parâmetro | Tipo | Obrigatório | Descrição |
|---|---|---|---|
| `transaction_id` | integer | sim | ≥ 1 |

**Saída (`structuredContent`)**: `transaction`

### `transactions_show` — Mostrar lançamento na conversa

- **Classe:** Leitura · **Escopo:** `finance.read` · **Custo:** 1 unidade(s)
- **Annotations:** readOnlyHint=true, destructiveHint=false, idempotentHint=true, openWorldHint=false
- **UI (MCP Apps):** `ui://controle-financeiro/widget-v3.html`

Desenha UM lançamento como cartão visual na conversa (valor, divisão, sua parte, cartão/fatura, parcelas) e devolve os mesmos dados de transactions_get.

Use quando: o usuário pedir para VER ou MOSTRAR um lançamento, ou quiser conferir visualmente o que acabou de ser registrado ou editado. Chame uma vez, no fim.

Não use quando: precisar dos dados para responder, analisar ou editar (transactions_get): cada chamada desenha um componente novo na conversa.

**Entrada**

| Parâmetro | Tipo | Obrigatório | Descrição |
|---|---|---|---|
| `transaction_id` | integer | sim | ≥ 1 |

**Saída (`structuredContent`)**: `transaction`

### `statements_get` — Ver fatura do cartão

- **Classe:** Leitura · **Escopo:** `finance.read` · **Custo:** 2 unidade(s)
- **Annotations:** readOnlyHint=true, destructiveHint=false, idempotentHint=true, openWorldHint=false

Devolve a fatura de um cartão de crédito: total, quanto já foi pago, saldo, vencimento, as compras (paginadas) e o total por categoria. Só dados; para DESENHAR a fatura na conversa, use statements_show.

Use quando: precisar dos números para responder ou analisar ('quanto vem na fatura', 'o que tem na fatura de outubro', comparar faturas).

Não use quando: o usuário pedir para ver/mostrar a fatura (statements_show); quiser só o limite disponível (cards_list); ou for pagar a fatura (statements_pay).

**Entrada**

| Parâmetro | Tipo | Obrigatório | Descrição |
|---|---|---|---|
| `card` | string | não | Nome do cartão. Omitido: seu único cartão. (máx. 120) |
| `card_id` | integer | não |  |
| `month` | string | não | Mês da fatura (YYYY-MM). Omitido: a fatura do ciclo atual. (padrão `^\d{4}-(0[1-9]|1[0-2])$`) |
| `limit` | integer | não | Compras por página (o total e as categorias já cobrem a fatura inteira). (≥ 1, ≤ 100) |
| `cursor` | string | não | máx. 512 |

**Saída (`structuredContent`)**: `card`, `currency`, `month`, `exists`, `status`, `closing_date`, `due_date`, `total`, `paid`, `balance`, `overdue`, `purchases_count`, `purchases`, `next_cursor`, `by_category`, `available_months`, `app_url`

### `statements_show` — Mostrar fatura na conversa

- **Classe:** Leitura · **Escopo:** `finance.read` · **Custo:** 2 unidade(s)
- **Annotations:** readOnlyHint=true, destructiveHint=false, idempotentHint=true, openWorldHint=false
- **UI (MCP Apps):** `ui://controle-financeiro/widget-v3.html`

Desenha a fatura de um cartão como componente visual na conversa (total, saldo, vencimento, as maiores categorias e as compras mais recentes) e devolve os mesmos dados de statements_get, só com a primeira página de compras.

Use quando: o usuário pedir para ver ou mostrar a fatura ('mostre minha fatura do Nubank'). Chame uma vez, com a fatura final.

Não use quando: precisar dos números para analisar, somar ou comparar (statements_get): cada chamada desenha um componente novo na conversa.

**Entrada**

| Parâmetro | Tipo | Obrigatório | Descrição |
|---|---|---|---|
| `card` | string | não | Nome do cartão. Omitido: seu único cartão. (máx. 120) |
| `card_id` | integer | não |  |
| `month` | string | não | Mês da fatura (YYYY-MM). Omitido: a fatura do ciclo atual. (padrão `^\d{4}-(0[1-9]|1[0-2])$`) |

**Saída (`structuredContent`)**: `card`, `currency`, `month`, `exists`, `status`, `closing_date`, `due_date`, `total`, `paid`, `balance`, `overdue`, `purchases_count`, `purchases`, `next_cursor`, `by_category`, `available_months`, `app_url`

### `reports_summary` — Resumo financeiro do mês

- **Classe:** Leitura · **Escopo:** `finance.read` · **Custo:** 2 unidade(s)
- **Annotations:** readOnlyHint=true, destructiveHint=false, idempotentHint=true, openWorldHint=false

Resumo do mês da pessoa somando todos os espaços: renda, SEU consumo (sua parte das despesas), resultado, caixa (entrou/saiu), quanto deve e tem a receber, contas a pagar e o consumo por categoria. Com `months` > 1, traz a evolução mês a mês. Só dados; para DESENHAR o resumo na conversa, use reports_show.

Use quando: 'quanto gastei com alimentação este mês?', 'como está meu mês?', 'gastei mais que em agosto?'.

Não use quando: o usuário pedir para ver/mostrar o resumo (reports_show); precisar dos lançamentos individuais (transactions_search) ou da fatura (statements_get).

**Entrada**

| Parâmetro | Tipo | Obrigatório | Descrição |
|---|---|---|---|
| `month` | string | não | Mês (YYYY-MM). Omitido: o mês atual. (padrão `^\d{4}-(0[1-9]|1[0-2])$`) |
| `months` | integer | não | Com N > 1, traz também a evolução dos últimos N meses (até o mês atual). (≥ 1, ≤ 12) |
| `space` | string | não | Restringe as categorias a um espaço. (máx. 120) |
| `space_id` | integer | não |  |
| `category` | string | não | Mostra só esta categoria. (máx. 120) |
| `currency` | string | não | Moeda dos totais pessoais (ISO-4217). (mín. 3, máx. 3) |

**Saída (`structuredContent`)**: `month`, `currency`, `income`, `consumption`, `result`, `cash_in`, `cash_out`, `to_pay`, `to_receive`, `payables_total`, `my_categories`, `spaces`, `series`, `excluded_foreign_count`, `app_url`

### `reports_show` — Mostrar resumo do mês na conversa

- **Classe:** Leitura · **Escopo:** `finance.read` · **Custo:** 2 unidade(s)
- **Annotations:** readOnlyHint=true, destructiveHint=false, idempotentHint=true, openWorldHint=false
- **UI (MCP Apps):** `ui://controle-financeiro/widget-v3.html`

Desenha o resumo de UM mês como componente visual na conversa (renda, seu consumo, caixa, a pagar, resultado e consumo por categoria) e devolve os mesmos dados de reports_summary.

Use quando: o usuário pedir para VER ou MOSTRAR o resumo ou o painel do mês ('mostre meu resumo de setembro'). Chame uma vez, com o mês final.

Não use quando: precisar dos números para responder ou analisar, ou da evolução de vários meses (reports_summary): cada chamada desenha um componente novo na conversa.

**Entrada**

| Parâmetro | Tipo | Obrigatório | Descrição |
|---|---|---|---|
| `month` | string | não | Mês (YYYY-MM). Omitido: o mês atual. (padrão `^\d{4}-(0[1-9]|1[0-2])$`) |
| `space` | string | não | Restringe as categorias a um espaço. (máx. 120) |
| `space_id` | integer | não |  |
| `category` | string | não | Mostra só esta categoria. (máx. 120) |
| `currency` | string | não | Moeda dos totais pessoais (ISO-4217). (mín. 3, máx. 3) |

**Saída (`structuredContent`)**: `month`, `currency`, `income`, `consumption`, `result`, `cash_in`, `cash_out`, `to_pay`, `to_receive`, `payables_total`, `my_categories`, `spaces`, `series`, `excluded_foreign_count`, `app_url`

### `budgets_list` — Orçamentos do mês

- **Classe:** Leitura · **Escopo:** `finance.read` · **Custo:** 2 unidade(s)
- **Annotations:** readOnlyHint=true, destructiveHint=false, idempotentHint=true, openWorldHint=false

Lista as metas de gasto (orçamentos) por categoria, com quanto já foi gasto e quanto resta. Meta pessoal compara com a SUA parte; meta da casa, com o total da casa.

Use quando: 'quanto ainda posso gastar em mercado?', 'estourei algum orçamento?'.

Não use quando: quiser definir uma meta (budgets_set).

**Entrada**

| Parâmetro | Tipo | Obrigatório | Descrição |
|---|---|---|---|
| `month` | string | não | Mês (YYYY-MM). Omitido: o mês atual. (padrão `^\d{4}-(0[1-9]|1[0-2])$`) |
| `space` | string | não | máx. 120 |
| `space_id` | integer | não |  |

**Saída (`structuredContent`)**: `month`, `budgets`

### `debts_summary` — Quem deve a quem

- **Classe:** Leitura · **Escopo:** `finance.read` · **Custo:** 2 unidade(s)
- **Annotations:** readOnlyHint=true, destructiveHint=false, idempotentHint=true, openWorldHint=false

Mostra quanto você deve e quanto te devem, por pessoa e por espaço (saldos de espaços diferentes não se compensam). Opcionalmente o retrato de um mês e o histórico de acertos.

Use quando: 'quanto o João está me devendo?', 'quanto eu devo pra Ana?', 'já acertei com o Pedro?'.

Não use quando: quiser registrar um pagamento entre pessoas (settlements_create).

**Entrada**

| Parâmetro | Tipo | Obrigatório | Descrição |
|---|---|---|---|
| `person` | string | não | Só o saldo com esta pessoa. (máx. 120) |
| `person_id` | integer | não |  |
| `space` | string | não | máx. 120 |
| `space_id` | integer | não |  |
| `month` | string | não | Retrato de UM mês (competência). Omitido: saldo acumulado. (padrão `^\d{4}-(0[1-9]|1[0-2])$`) |
| `include_history` | boolean | não | Inclui os últimos acertos registrados. |
| `history_limit` | integer | não | ≥ 1, ≤ 50 |
| `currency` | string | não | mín. 3, máx. 3 |

**Saída (`structuredContent`)**: `scope`, `month`, `currency`, `to_pay`, `to_receive`, `spaces`, `history`

### `payables_list` — Contas a pagar

- **Classe:** Leitura · **Escopo:** `finance.read` · **Custo:** 2 unidade(s)
- **Annotations:** readOnlyHint=true, destructiveHint=false, idempotentHint=true, openWorldHint=false

Lista o que você ainda tem a pagar: contas do mês fora do cartão (boletos, Pix agendado, recorrências), faturas de cartão e parcelas de financiamento, com vencimento e atrasos.

Use quando: 'o que tenho pra pagar este mês?', 'tem conta atrasada?', 'quando vence a fatura?'.

Não use quando: quiser marcar algo como pago (transactions_update com paid=true, ou statements_pay para fatura).

**Entrada**

| Parâmetro | Tipo | Obrigatório | Descrição |
|---|---|---|---|
| `month` | string | não | Mês (YYYY-MM). Omitido: o mês atual. (padrão `^\d{4}-(0[1-9]|1[0-2])$`) |
| `space` | string | não | máx. 120 |
| `space_id` | integer | não |  |
| `include_overdue` | boolean | não | Inclui o que venceu em meses anteriores e segue em aberto. |

**Saída (`structuredContent`)**: `month`, `currency`, `bills_total`, `overdue_total`, `bills`, `card_bills`, `financings`

### `income_list` — Rendas do mês

- **Classe:** Leitura · **Escopo:** `finance.read` · **Custo:** 1 unidade(s)
- **Annotations:** readOnlyHint=true, destructiveHint=false, idempotentHint=true, openWorldHint=false

Lista suas rendas (salário, freelas, reembolsos) do mês, com situação: prevista, recebida, atrasada ou cancelada.

Use quando: 'meu salário caiu?', 'quanto vou receber este mês?'.

Não use quando: quiser registrar ou marcar renda como recebida (income_create / income_update).

**Entrada**

| Parâmetro | Tipo | Obrigatório | Descrição |
|---|---|---|---|
| `month` | string | não | Competência (YYYY-MM). Omitido: o mês atual. (padrão `^\d{4}-(0[1-9]|1[0-2])$`) |
| `status` | `expected` \| `received` \| `overdue` \| `cancelled` | não |  |

**Saída (`structuredContent`)**: `month`, `currency_totals`, `incomes`

### `recurring_list` — Despesas e rendas recorrentes

- **Classe:** Leitura · **Escopo:** `finance.read` · **Custo:** 1 unidade(s)
- **Annotations:** readOnlyHint=true, destructiveHint=false, idempotentHint=true, openWorldHint=false

Lista suas despesas recorrentes (aluguel, assinaturas, contas fixas) por espaço e suas rendas recorrentes (salário), com valor, frequência e se ainda estão ativas.

Use quando: 'quais são minhas assinaturas?', 'quanto pago de contas fixas?', ou antes de editar uma recorrência (recurring_update precisa do id).

Não use quando: quiser os lançamentos já gerados (transactions_search).

**Entrada**

| Parâmetro | Tipo | Obrigatório | Descrição |
|---|---|---|---|
| `space` | string | não | máx. 120 |
| `space_id` | integer | não |  |
| `kind` | `all` \| `expense` \| `income` | não |  |
| `active_only` | boolean | não |  |

**Saída (`structuredContent`)**: `items`

### `transactions_create` — Registrar despesa

- **Classe:** Escrita · **Escopo:** `transactions.write` · **Custo:** 3 unidade(s)
- **Annotations:** readOnlyHint=false, destructiveHint=false, idempotentHint=true, openWorldHint=false
- **Idempotência:** `idempotency_key` obrigatória (replay devolve o mesmo resultado; outra carga com a mesma chave = `CONFLICT`).

Registra uma despesa (compra, conta, gasto) numa única chamada atômica: valor, data, categoria, tags, cartão e parcelas, quem pagou, divisão com outras pessoas, conta de origem, moeda estrangeira e se já foi paga. O servidor calcula a fatura, as parcelas e os centavos da divisão — não calcule nada disso.

Use quando: o usuário disser que comprou/gastou/pagou algo ("adicione R$ 89,90 de gasolina no Nubank", "comprei uma TV de R$ 3.000 em 10x", "jantar de 120, metade do João").

Não use quando: for renda (income_create), transferência entre contas (transfers_create), pagamento de fatura (statements_pay) ou acerto de dívida entre pessoas (settlements_create); nem para corrigir um lançamento existente (transactions_update).

Espaço: informe `space` quando o usuário disser. Omitido, vale o ÚNICO espaço que tem todas as pessoas citadas (sem ninguém citado: seu espaço pessoal); se houver dúvida volta AMBIGUOUS — pergunte ao usuário. Nomes (cartão, categoria, pessoa) ambíguos também voltam AMBIGUOUS com candidatos; repita a chamada com o `*_id` escolhido e a MESMA idempotency_key.

Divisão: `split_with` = partes iguais entre você e as pessoas; `split` = partes desiguais (valor ou percentual de cada um). Sem divisão, a despesa é toda sua.

Gere uma idempotency_key nova para cada despesa e reutilize-a só ao repetir a mesma chamada.

**Entrada**

| Parâmetro | Tipo | Obrigatório | Descrição |
|---|---|---|---|
| `idempotency_key` | string | sim | Identificador ÚNICO desta intenção do usuário (ex.: um UUID novo). Repita a MESMA chave só ao reenviar exatamente a mesma chamada após erro de rede ou timeout — assim nada é criado em dobro. Pedido novo = chave nova. (mín. 8, máx. 100, padrão `^[A-Za-z0-9._:-]+$`) |
| `title` | string | sim | Descrição curta, como aparece na lista (ex.: "Gasolina"). (mín. 1, máx. 200) |
| `amount` | string | sim | Valor TOTAL da compra (nas parceladas, o total, não a parcela). (padrão `^\d{1,16}([.,]\d{1,2})?$`) |
| `date` | data `YYYY-MM-DD` | não | Dia da compra. Omitido = hoje (profile_get.today). |
| `space` | string | não | Espaço onde lançar. Omitido = regra do espaço implícito (ver descrição). (máx. 120) |
| `space_id` | integer | não |  |
| `description` | string | não | Observação livre. (máx. 2000) |
| `currency` | string | não | Moeda ISO 4217 da compra (ex.: USD). Estrangeira é convertida para a moeda do espaço na data (PTAX; IOF no cartão). (padrão `^[A-Za-z]{3}$`) |
| `category` | string | não | Nome de uma categoria EXISTENTE do espaço. (máx. 120) |
| `category_id` | integer | não |  |
| `tags` | lista de string | não | Nomes de tags EXISTENTES do espaço. (máx. 10) |
| `card` | string | não | Cartão de crédito seu (nome). Define pagamento no crédito. (máx. 120) |
| `card_id` | integer | não |  |
| `installments` | integer | não | Número de parcelas (exige cartão). (≥ 2, ≤ 36) |
| `statement_shift` | integer | não | Raro: o emissor lançou a compra noutra fatura (+1 = próxima). Só com cartão. (≥ -1, ≤ 2) |
| `payment_method` | `credit_card` \| `debit_card` \| `pix` \| `cash` \| `bank_transfer` \| `boleto` \| `other` | não | Forma de pagamento fora do cartão (pix, debit_card, cash…). |
| `settled` | boolean | não | Já foi paga? Omitido = o app decide pela data (passado = pago; futuro = a pagar). Não se aplica a cartão. |
| `paid_by` | string | não | Quem pagou (nome de um membro do espaço). Omitido = você. (máx. 120) |
| `paid_by_id` | integer | não |  |
| `account` | string | não | Conta de onde saiu o dinheiro (só quando quem pagou foi você; não use para cartão). (máx. 120) |
| `account_id` | integer | não |  |
| `split_with` | lista de string | não | Divide em partes IGUAIS entre você e estas pessoas (nomes de membros do espaço). Ex.: ["João"] = metade sua, metade do João. (máx. 20) |
| `split_with_ids` | lista de integer | não | máx. 20 |
| `split` | lista de objeto | não | Divisão desigual: a parte de CADA participante (inclua você, se tiver parte). Todas por valor (somando o total) ou todas por percentual (somando 100). (mín. 1, máx. 20) |

**Saída (`structuredContent`)**: `transaction`, `installments`, `replayed`

Exemplo:

```json
{"title": "Gasolina", "amount": "89.90", "card": "Nubank", "category": "Transporte", "idempotency_key": "b3f1c2d4-0001"}
```

Exemplo:

```json
{"title": "TV", "amount": "3000.00", "card": "Nubank", "installments": 10, "idempotency_key": "b3f1c2d4-0002"}
```

Exemplo:

```json
{"title": "Jantar", "amount": "120.00", "split_with": ["João"], "payment_method": "pix", "idempotency_key": "b3f1c2d4-0003"}
```

### `transactions_update` — Editar lançamento

- **Classe:** Escrita · **Escopo:** `transactions.write` · **Custo:** 3 unidade(s)
- **Annotations:** readOnlyHint=false, destructiveHint=true, idempotentHint=true, openWorldHint=false

Altera um lançamento existente: título, observação, valor, data, categoria, tags, cartão, forma de pagamento, quem pagou, divisão, moeda (o valor é convertido na data, com IOF no cartão), "já paguei" (settled) ou cancelamento. Só os campos informados mudam. Devolve como estava ANTES (`previous`) e o que mudou (`changed`).

Use quando: o usuário pedir para corrigir ou completar um lançamento ("troque a categoria daquela compra para Alimentação", "metade dessa compra é do João", "marque como paga").

Não use quando: ainda não tiver o `transaction_id` (busque com transactions_search); para categorizar muitos de uma vez (transactions_bulk_preview); para excluir (transactions_delete).

Parcelada: `scope=installment` (padrão) muda só a parcela; `scope=purchase` muda a compra inteira (total, nº de parcelas, divisão, categoria) — pergunte ao usuário se não estiver claro.

Despesa paga não muda até ser reaberta (`status=confirmed`); cancelada é definitiva.

**Entrada**

| Parâmetro | Tipo | Obrigatório | Descrição |
|---|---|---|---|
| `transaction_id` | integer | sim |  |
| `scope` | `installment` \| `purchase` | não | Só para compra parcelada: `installment` muda só esta parcela; `purchase` muda a compra inteira (total, nº de parcelas, divisão, categoria), recalculando as parcelas em aberto. |
| `title` | string | não | mín. 1, máx. 200 |
| `description` | string | não | Texto novo; "" apaga a observação. (máx. 2000) |
| `amount` | string | não | Novo valor total, na moeda DA COMPRA: a de `currency`, se informada; senão a original (`foreign.original_currency`) quando o lançamento foi convertido. (padrão `^\d{1,16}([.,]\d{1,2})?$`) |
| `currency` | string | não | Moeda ISO 4217 da compra (ex.: USD). Estrangeira é convertida para a moeda do espaço na data (PTAX; IOF no cartão). (padrão `^[A-Za-z]{3}$`) |
| `date` | data `YYYY-MM-DD` | não | Dia civil no fuso da conta (ver profile_get.timezone), formato YYYY-MM-DD. |
| `category` | string | não | Nova categoria (existente no espaço). (máx. 120) |
| `category_id` | integer | não |  |
| `remove_category` | boolean | não | true = deixa o lançamento sem categoria. |
| `tags` | lista de string | não | Substitui TODAS as tags ([] remove todas). (máx. 10) |
| `card` | string | não | Passa a compra para este cartão seu. (máx. 120) |
| `card_id` | integer | não |  |
| `payment_method` | `credit_card` \| `debit_card` \| `pix` \| `cash` \| `bank_transfer` \| `boleto` \| `other` | não | Nova forma de pagamento (fora do cartão remove o cartão). |
| `statement_shift` | integer | não | ≥ -1, ≤ 2 |
| `installments` | integer | não | Novo nº de parcelas (só com scope=purchase). (≥ 2, ≤ 36) |
| `settled` | boolean | não | true = já paguei; false = ainda a pagar. Compra no cartão se paga pela fatura. |
| `status` | `confirmed` \| `cancelled` | não | `cancelled` = cancelar (definitivo: deixa de contar, continua visível); `confirmed` = reabrir despesa marcada como paga. |
| `paid_by` | string | não | Quem pagou (nome de um membro do espaço). Omitido = você. (máx. 120) |
| `paid_by_id` | integer | não |  |
| `account` | string | não | Conta de onde saiu o dinheiro (só quando quem pagou foi você; não use para cartão). (máx. 120) |
| `account_id` | integer | não |  |
| `split_with` | lista de string | não | Divide em partes IGUAIS entre você e estas pessoas (nomes de membros do espaço). Ex.: ["João"] = metade sua, metade do João. (máx. 20) |
| `split_with_ids` | lista de integer | não | máx. 20 |
| `split` | lista de objeto | não | Divisão desigual: a parte de CADA participante (inclua você, se tiver parte). Todas por valor (somando o total) ou todas por percentual (somando 100). (mín. 1, máx. 20) |

**Saída (`structuredContent`)**: `transaction`, `previous`, `changed`, `installments`

Exemplo:

```json
{"transaction_id": 123, "category": "Alimentação"}
```

Exemplo:

```json
{"transaction_id": 123, "split_with": ["João"]}
```

Exemplo:

```json
{"transaction_id": 123, "settled": true}
```

Exemplo:

```json
{"transaction_id": 456, "scope": "purchase", "amount": "2800.00"}
```

### `transactions_delete` — Excluir lançamento

- **Classe:** Destrutiva · **Escopo:** `transactions.write` · **Custo:** 3 unidade(s)
- **Annotations:** readOnlyHint=false, destructiveHint=true, idempotentHint=true, openWorldHint=false

Exclui um lançamento (ou, com `scope=purchase`, todas as parcelas em aberto de uma compra parcelada). A exclusão pode ser desfeita com transactions_restore. Despesa paga não é excluída — reabra antes.

Use quando: o usuário pedir para apagar um lançamento específico que você já identificou (mostre qual é antes: título, data, valor).

Não use quando: forem vários lançamentos (use transactions_bulk_preview + transactions_bulk_delete) ou houver dúvida sobre qual lançamento é — pergunte.

Se o lançamento tiver anexos (recibos), eles seriam apagados para sempre: a tool recusa e pede o fluxo com prévia (transactions_bulk_preview com action=delete), que mostra isso ao usuário.

**Entrada**

| Parâmetro | Tipo | Obrigatório | Descrição |
|---|---|---|---|
| `transaction_id` | integer | sim |  |
| `scope` | `installment` \| `purchase` | não | Parcelada: `installment` exclui só esta parcela; `purchase` exclui todas as parcelas em aberto da compra. |

**Saída (`structuredContent`)**: `deleted`, `skipped_paid`, `restorable`

Exemplo:

```json
{"transaction_id": 123}
```

Exemplo:

```json
{"transaction_id": 456, "scope": "purchase"}
```

### `transactions_restore` — Restaurar lançamento excluído

- **Classe:** Escrita · **Escopo:** `transactions.write` · **Custo:** 3 unidade(s)
- **Annotations:** readOnlyHint=false, destructiveHint=false, idempotentHint=true, openWorldHint=false

Desfaz a exclusão de um lançamento (volta a contar em tudo). Anexos apagados não voltam.

Use quando: o usuário pedir para desfazer uma exclusão recente, com o id devolvido por transactions_delete ou transactions_bulk_delete.

Não use quando: o lançamento não foi excluído (nada acontece) ou para cancelar/reabrir (transactions_update).

**Entrada**

| Parâmetro | Tipo | Obrigatório | Descrição |
|---|---|---|---|
| `transaction_id` | integer | sim |  |

**Saída (`structuredContent`)**: `transaction`, `installments`, `replayed`

Exemplo:

```json
{"transaction_id": 123}
```

### `transactions_bulk_preview` — Prévia de ação em massa

- **Classe:** Leitura · **Escopo:** `finance.read` · **Custo:** 3 unidade(s)
- **Annotations:** readOnlyHint=true, destructiveHint=false, idempotentHint=true, openWorldHint=false
- **UI (MCP Apps):** `ui://controle-financeiro/widget-v3.html`

Primeiro passo OBRIGATÓRIO para excluir ou categorizar vários lançamentos (ou um lançamento com anexos). Não altera nada: calcula o conjunto exato, o total, uma amostra e o que ficou de fora, e devolve um `confirmation_token` válido por 10 minutos.

Use quando: o usuário pedir para apagar/categorizar vários lançamentos ("apague as compras do McDonald's deste mês", "categorize tudo sem categoria de setembro como Mercado").

Não use quando: for um único lançamento sem anexos (transactions_delete/transactions_update).

Depois: MOSTRE count, total e amostra ao usuário e só com a confirmação dele chame transactions_bulk_delete ou transactions_bulk_categorize com o token. Categorizar só alcança lançamentos SEM categoria.

**Entrada**

| Parâmetro | Tipo | Obrigatório | Descrição |
|---|---|---|---|
| `action` | `delete` \| `categorize` | sim | O que fazer com o conjunto. |
| `transaction_ids` | lista de integer | não | Ids exatos (de transactions_search). Use isto OU `filters`. (mín. 1, máx. 200) |
| `filters` | objeto | não | Os mesmos filtros de transactions_search (ao menos um). Use isto OU `transaction_ids`. |
| `category` | string | não | Categoria a aplicar (action=categorize). (máx. 120) |
| `category_id` | integer | não |  |

**Saída (`structuredContent`)**: `action`, `count`, `totals`, `sample`, `ineligible_count`, `ineligible`, `not_found_ids`, `attachments`, `category`, `space`, `confirmation_token`, `expires_at`, `next_step`

Exemplo:

```json
{"action": "delete", "filters": {"text": "McDonald's", "month": "2026-09"}}
```

Exemplo:

```json
{"action": "categorize", "filters": {"uncategorized": true, "month": "2026-09"}, "category": "Mercado"}
```

### `transactions_bulk_delete` — Excluir em massa (confirmado)

- **Classe:** Destrutiva · **Escopo:** `transactions.write` · **Custo:** 5 unidade(s)
- **Annotations:** readOnlyHint=false, destructiveHint=true, idempotentHint=true, openWorldHint=false

Executa a exclusão preparada por transactions_bulk_preview (action=delete). Recebe só o `confirmation_token`: exclui exatamente o conjunto da prévia, tudo ou nada. Se algo mudou desde a prévia (lançamento pago, apagado, fora do seu alcance), nada é excluído e é preciso nova prévia. Anexos dos excluídos são apagados para sempre; os lançamentos podem ser restaurados um a um com transactions_restore.

Use quando: o usuário CONFIRMOU a prévia que você mostrou.

Não use quando: não houver prévia confirmada pelo usuário nesta conversa.

**Entrada**

| Parâmetro | Tipo | Obrigatório | Descrição |
|---|---|---|---|
| `confirmation_token` | string | sim | O `confirmation_token` devolvido pela prévia (transactions_bulk_preview). (mín. 20, máx. 128, padrão `^cfm_cf_[A-Za-z0-9_-]+$`) |

**Saída (`structuredContent`)**: `action`, `count`, `transaction_ids`, `skipped`, `attachments_removed`, `replayed`

Exemplo:

```json
{"confirmation_token": "cfm_cf_…"}
```

### `transactions_bulk_categorize` — Categorizar em massa (confirmado)

- **Classe:** Escrita · **Escopo:** `transactions.write` · **Custo:** 5 unidade(s)
- **Annotations:** readOnlyHint=false, destructiveHint=true, idempotentHint=true, openWorldHint=false

Executa a categorização preparada por transactions_bulk_preview (action=categorize). Recebe só o `confirmation_token` e aplica a categoria da prévia aos lançamentos da prévia que continuam sem categoria.

Use quando: o usuário CONFIRMOU a prévia que você mostrou.

Não use quando: não houver prévia confirmada; para trocar a categoria de um lançamento específico use transactions_update.

**Entrada**

| Parâmetro | Tipo | Obrigatório | Descrição |
|---|---|---|---|
| `confirmation_token` | string | sim | O `confirmation_token` devolvido pela prévia (transactions_bulk_preview). (mín. 20, máx. 128, padrão `^cfm_cf_[A-Za-z0-9_-]+$`) |

**Saída (`structuredContent`)**: `action`, `count`, `transaction_ids`, `skipped`, `attachments_removed`, `replayed`

Exemplo:

```json
{"confirmation_token": "cfm_cf_…"}
```

### `imports_preview` — Conferir linhas de extrato

- **Classe:** Leitura · **Escopo:** `finance.read` · **Custo:** 3 unidade(s)
- **Annotations:** readOnlyHint=true, destructiveHint=false, idempotentHint=true, openWorldHint=false

Confere linhas de um extrato bancário/cartão contra o que já está no app, sem gravar nada: marca o que já foi importado e o que parece já lançado.

Use quando: o usuário colar ou enviar um extrato e pedir para conciliar/importar. Extraia as linhas de SAÍDA (data, descrição, valor) e chame esta tool antes de imports_commit.

Não use quando: for registrar um gasto isolado (transactions_create).

**Entrada**

| Parâmetro | Tipo | Obrigatório | Descrição |
|---|---|---|---|
| `space` | string | não | Espaço onde os lançamentos entram. (máx. 120) |
| `space_id` | integer | não |  |
| `rows` | lista de objeto | sim | mín. 1, máx. 200 |

**Saída (`structuredContent`)**: `space`, `rows`, `new_count`, `already_imported_count`, `possible_duplicate_count`

Exemplo:

```json
{"space": "Meu espaço", "rows": [{"date": "2026-09-20", "title": "PADARIA PAO QUENTE", "amount": "12.50"}]}
```

### `imports_commit` — Importar linhas de extrato

- **Classe:** Escrita · **Escopo:** `transactions.write` · **Custo:** 5 unidade(s)
- **Annotations:** readOnlyHint=false, destructiveHint=false, idempotentHint=true, openWorldHint=false
- **Idempotência:** `idempotency_key` obrigatória (replay devolve o mesmo resultado; outra carga com a mesma chave = `CONFLICT`).

Grava as linhas de extrato confirmadas pelo usuário como lançamentos (pagos por você, 100% seus, já liquidados na data), num lote. Linhas já importadas antes são puladas sozinhas.

Use quando: depois de imports_preview, o usuário confirmar quais linhas importar.

Não use quando: não houver confirmação do usuário, ou para despesas divididas/no cartão (transactions_create, que tem divisão e fatura).

Mande `decision: ignore` nas linhas que o usuário descartou (ficam registradas como ignoradas).

**Entrada**

| Parâmetro | Tipo | Obrigatório | Descrição |
|---|---|---|---|
| `space` | string | não | Espaço onde os lançamentos entram. (máx. 120) |
| `space_id` | integer | não |  |
| `idempotency_key` | string | sim | Identificador ÚNICO desta intenção do usuário (ex.: um UUID novo). Repita a MESMA chave só ao reenviar exatamente a mesma chamada após erro de rede ou timeout — assim nada é criado em dobro. Pedido novo = chave nova. (mín. 8, máx. 100, padrão `^[A-Za-z0-9._:-]+$`) |
| `label` | string | não | Nome do lote (ex.: "Extrato Itaú setembro"). (máx. 120) |
| `rows` | lista de objeto | sim | mín. 1, máx. 200 |

**Saída (`structuredContent`)**: `batch_id`, `space`, `imported`, `ignored`, `duplicate`, `skipped`, `transaction_ids`, `replayed`

Exemplo:

```json
{"idempotency_key": "a9b8c7d6-0001", "space": "Meu espaço", "label": "Extrato Itaú", "rows": [{"date": "2026-09-20", "title": "PADARIA PAO QUENTE", "amount": "12.50"}]}
```

### `statements_pay` — Pagar fatura do cartão

- **Classe:** Escrita · **Escopo:** `accounts.write` · **Custo:** 3 unidade(s)
- **Annotations:** readOnlyHint=false, destructiveHint=false, idempotentHint=true, openWorldHint=false
- **Idempotência:** `idempotency_key` obrigatória (replay devolve o mesmo resultado; outra carga com a mesma chave = `CONFLICT`).

Registra o pagamento (total ou parcial) de uma fatura do cartão de crédito cujo ciclo já fechou, com a conta de onde o dinheiro saiu. Não é despesa: as compras já estão na fatura.

Use quando: o usuário disser que pagou a fatura ("paguei a fatura do Nubank", "paguei R$ 500 da fatura de setembro pelo Itaú").

Não use quando: for uma compra no cartão (transactions_create) ou a fatura ainda estiver em curso (antes da data de fechamento). Fatura com o ciclo encerrado e ainda aberta no app é fechada e paga na mesma operação.

Sem `amount`, paga o saldo inteiro. Pagamento acima do saldo é recusado.

**Entrada**

| Parâmetro | Tipo | Obrigatório | Descrição |
|---|---|---|---|
| `idempotency_key` | string | sim | Identificador ÚNICO desta intenção do usuário (ex.: um UUID novo). Repita a MESMA chave só ao reenviar exatamente a mesma chamada após erro de rede ou timeout — assim nada é criado em dobro. Pedido novo = chave nova. (mín. 8, máx. 100, padrão `^[A-Za-z0-9._:-]+$`) |
| `card` | string | não | Cartão (nome). Omitido: seu único cartão. (máx. 120) |
| `card_id` | integer | não |  |
| `month` | string | não | Mês da fatura (YYYY-MM). Omitido: a única fatura fechada com saldo em aberto. (padrão `^\d{4}-(0[1-9]|1[0-2])$`) |
| `amount` | string | não | Valor pago. Omitido = o saldo inteiro da fatura. (padrão `^\d{1,16}([.,]\d{1,2})?$`) |
| `account` | string | não | Conta de onde saiu o dinheiro. (máx. 120) |
| `account_id` | integer | não |  |
| `paid_on` | data `YYYY-MM-DD` | não | Dia do pagamento. Omitido = hoje. |
| `note` | string | não | máx. 2000 |

**Saída (`structuredContent`)**: `card`, `month`, `payment_id`, `amount_paid`, `currency`, `status`, `total`, `paid`, `balance`, `due_date`, `account`, `closed_now`, `replayed`, `app_url`

Exemplo:

```json
{"idempotency_key": "c7d1e2f3-0001", "card": "Nubank", "month": "2026-09", "account": "Itaú"}
```

### `transfers_create` — Transferir entre contas

- **Classe:** Escrita · **Escopo:** `accounts.write` · **Custo:** 3 unidade(s)
- **Annotations:** readOnlyHint=false, destructiveHint=false, idempotentHint=true, openWorldHint=false
- **Idempotência:** `idempotency_key` obrigatória (replay devolve o mesmo resultado; outra carga com a mesma chave = `CONFLICT`).

Registra dinheiro que passou de uma conta sua para outra conta sua (ex.: da conta corrente para a poupança). Não é despesa nem renda: só move saldo.

Use quando: o usuário disser que transferiu/moveu dinheiro entre as próprias contas.

Não use quando: pagar alguém (transactions_create), quitar dívida com outra pessoa (settlements_create) ou pagar fatura (statements_pay).

Contas em moedas diferentes exigem `to_amount` (quanto entrou): o app não inventa câmbio.

**Entrada**

| Parâmetro | Tipo | Obrigatório | Descrição |
|---|---|---|---|
| `idempotency_key` | string | sim | Identificador ÚNICO desta intenção do usuário (ex.: um UUID novo). Repita a MESMA chave só ao reenviar exatamente a mesma chamada após erro de rede ou timeout — assim nada é criado em dobro. Pedido novo = chave nova. (mín. 8, máx. 100, padrão `^[A-Za-z0-9._:-]+$`) |
| `from_account` | string | não | Conta de origem (nome). (máx. 120) |
| `from_account_id` | integer | não |  |
| `to_account` | string | não | Conta de destino (nome). (máx. 120) |
| `to_account_id` | integer | não |  |
| `amount` | string | sim | Valor que SAIU da conta de origem. (padrão `^\d{1,16}([.,]\d{1,2})?$`) |
| `to_amount` | string | não | Só entre moedas diferentes: quanto ENTROU no destino (o app não converte sozinho). (padrão `^\d{1,16}([.,]\d{1,2})?$`) |
| `date` | data `YYYY-MM-DD` | não | Dia da transferência. Omitido = hoje. |
| `note` | string | não | máx. 2000 |

**Saída (`structuredContent`)**: `id`, `from_account`, `to_account`, `from_amount`, `to_amount`, `from_currency`, `to_currency`, `exchange_rate`, `date`, `note`, `replayed`

Exemplo:

```json
{"idempotency_key": "c7d1e2f3-0002", "from_account": "Itaú", "to_account": "Poupança", "amount": "500.00"}
```

### `accounts_adjust_balance` — Conciliar saldo da conta

- **Classe:** Escrita · **Escopo:** `accounts.write` · **Custo:** 3 unidade(s)
- **Annotations:** readOnlyHint=false, destructiveHint=false, idempotentHint=true, openWorldHint=false
- **Idempotência:** `idempotency_key` obrigatória (replay devolve o mesmo resultado; outra carga com a mesma chave = `CONFLICT`).

Acerta o saldo de uma conta com o que o banco mostra: você informa o saldo REAL e o app lança a diferença como uma linha de ajuste datada (não é renda nem despesa e não reescreve o passado).

Use quando: o usuário disser "o banco mostra R$ 4.900, o app diz outra coisa" ou pedir para conciliar o saldo. Confira antes com accounts_list e mostre a diferença ao usuário.

Não use quando: faltar lançar despesas/rendas específicas — registre-as, que o saldo fecha sozinho.

**Entrada**

| Parâmetro | Tipo | Obrigatório | Descrição |
|---|---|---|---|
| `idempotency_key` | string | sim | Identificador ÚNICO desta intenção do usuário (ex.: um UUID novo). Repita a MESMA chave só ao reenviar exatamente a mesma chamada após erro de rede ou timeout — assim nada é criado em dobro. Pedido novo = chave nova. (mín. 8, máx. 100, padrão `^[A-Za-z0-9._:-]+$`) |
| `account` | string | não | Conta (nome). (máx. 120) |
| `account_id` | integer | não |  |
| `real_balance` | string | sim | O saldo REAL que o banco mostra (não a diferença). (padrão `^-?\d{1,16}([.,]\d{1,2})?$`) |
| `date` | data `YYYY-MM-DD` | não | Dia a que o saldo real se refere. Omitido = hoje. |
| `note` | string | não | Motivo (aparece no extrato). (máx. 2000) |

**Saída (`structuredContent`)**: `id`, `account`, `currency`, `date`, `previous_balance`, `new_balance`, `adjustment`, `replayed`

Exemplo:

```json
{"idempotency_key": "c7d1e2f3-0003", "account": "Itaú", "real_balance": "4900.00"}
```

### `income_create` — Registrar renda

- **Classe:** Escrita · **Escopo:** `income.write` · **Custo:** 3 unidade(s)
- **Annotations:** readOnlyHint=false, destructiveHint=false, idempotentHint=true, openWorldHint=false
- **Idempotência:** `idempotency_key` obrigatória (replay devolve o mesmo resultado; outra carga com a mesma chave = `CONFLICT`).

Registra uma entrada de dinheiro pessoal: salário, freela, reembolso, venda. Renda é sua, não de um espaço, e não se divide.

Use quando: o usuário disser que recebeu ou vai receber dinheiro ("caiu meu salário de R$ 5.000", "vou receber R$ 800 do freela dia 10").

Não use quando: alguém te pagou uma dívida de despesa dividida (settlements_create) ou foi transferência entre suas contas (transfers_create).

**Entrada**

| Parâmetro | Tipo | Obrigatório | Descrição |
|---|---|---|---|
| `idempotency_key` | string | sim | Identificador ÚNICO desta intenção do usuário (ex.: um UUID novo). Repita a MESMA chave só ao reenviar exatamente a mesma chamada após erro de rede ou timeout — assim nada é criado em dobro. Pedido novo = chave nova. (mín. 8, máx. 100, padrão `^[A-Za-z0-9._:-]+$`) |
| `title` | string | sim | Ex.: "Salário", "Freela site". (mín. 1, máx. 200) |
| `amount` | string | sim | Valor em string decimal com ponto e até 2 casas, ex.: "89.90". (padrão `^\d{1,16}([.,]\d{1,2})?$`) |
| `date` | data `YYYY-MM-DD` | não | Data da renda (competência). Omitido = hoje. |
| `currency` | string | não | Moeda ISO; estrangeira é convertida na data. (padrão `^[A-Za-z]{3}$`) |
| `category` | string | não | Rótulo livre da renda (ex.: "Salário", "Freela"). (máx. 60) |
| `description` | string | não | máx. 2000 |
| `account` | string | não | Conta onde o dinheiro caiu/vai cair. (máx. 120) |
| `account_id` | integer | não |  |
| `received` | boolean | não | Já caiu na conta? Omitido = o app decide pela data (passado/hoje = recebida). |

**Saída (`structuredContent`)**: `income`, `replayed`

Exemplo:

```json
{"idempotency_key": "d8e9f0a1-0001", "title": "Salário", "amount": "5000.00", "account": "Itaú"}
```

### `income_update` — Atualizar renda

- **Classe:** Escrita · **Escopo:** `income.write` · **Custo:** 3 unidade(s)
- **Annotations:** readOnlyHint=false, destructiveHint=true, idempotentHint=true, openWorldHint=false

Altera uma renda sua (valor, data, título, categoria, conta) e/ou o estado dela: recebida, prevista de novo ou cancelada. Devolve como estava antes (`previous`).

Use quando: o usuário disser "o salário caiu", "o freela atrasou, ainda não recebi", "esse pagamento não vai vir" ou pedir para corrigir uma renda. Pegue o `income_id` em income_list.

Não use quando: for registrar uma renda nova (income_create).

**Entrada**

| Parâmetro | Tipo | Obrigatório | Descrição |
|---|---|---|---|
| `income_id` | integer | sim |  |
| `title` | string | não | mín. 1, máx. 200 |
| `description` | string | não | máx. 2000 |
| `amount` | string | não | Novo valor, na moeda DA RENDA: a de `currency`, se informada; senão a original (`original_currency`) quando a renda foi convertida. (padrão `^\d{1,16}([.,]\d{1,2})?$`) |
| `currency` | string | não | Moeda ISO; estrangeira é reconvertida na data. (padrão `^[A-Za-z]{3}$`) |
| `date` | data `YYYY-MM-DD` | não | Nova data da renda (competência). |
| `category` | string | não | Rótulo livre da renda (ex.: "Salário", "Freela"). (máx. 60) |
| `account` | string | não | máx. 120 |
| `account_id` | integer | não |  |
| `status` | `received` \| `expected` \| `cancelled` | não | `received` = caiu na conta (use `received_on`/`account` se souber); `expected` = desfaz o "recebi"; `cancelled` = não veio e não virá (definitivo, continua visível). |
| `received_on` | data `YYYY-MM-DD` | não | Dia em que caiu (com status=received). Omitido = hoje. |

**Saída (`structuredContent`)**: `income`, `previous`, `changed`

Exemplo:

```json
{"income_id": 12, "status": "received", "account": "Itaú"}
```

Exemplo:

```json
{"income_id": 12, "amount": "5200.00"}
```

### `settlements_create` — Registrar acerto entre pessoas

- **Classe:** Escrita · **Escopo:** `settlements.write` · **Custo:** 3 unidade(s)
- **Annotations:** readOnlyHint=false, destructiveHint=false, idempotentHint=true, openWorldHint=false
- **Idempotência:** `idempotency_key` obrigatória (replay devolve o mesmo resultado; outra carga com a mesma chave = `CONFLICT`).

Registra que uma pessoa pagou a outra para quitar (toda ou parte da) dívida de despesas divididas num espaço. Reduz "quem deve a quem".

Use quando: o usuário disser "o João me pagou os R$ 45", "acertei com a Maria", "paguei minha parte do aluguel pro João". Confira o valor devido com debts_summary.

Não use quando: for uma despesa nova (transactions_create) ou renda (income_create).

O valor não pode passar da dívida naquela direção. Num espaço em que você é `member`, só é possível registrar acertos em que VOCÊ pagou (o outro lado registra o dele).

**Entrada**

| Parâmetro | Tipo | Obrigatório | Descrição |
|---|---|---|---|
| `idempotency_key` | string | sim | Identificador ÚNICO desta intenção do usuário (ex.: um UUID novo). Repita a MESMA chave só ao reenviar exatamente a mesma chamada após erro de rede ou timeout — assim nada é criado em dobro. Pedido novo = chave nova. (mín. 8, máx. 100, padrão `^[A-Za-z0-9._:-]+$`) |
| `person` | string | não | A outra pessoa do acerto (membro do espaço). (máx. 120) |
| `person_id` | integer | não |  |
| `direction` | `they_paid_me` \| `i_paid_them` | sim | `they_paid_me` = a pessoa te pagou; `i_paid_them` = você pagou a pessoa. |
| `amount` | string | sim | Valor pago. Não pode passar da dívida (veja debts_summary). (padrão `^\d{1,16}([.,]\d{1,2})?$`) |
| `space` | string | não | Espaço da dívida. Omitido: o único que vocês dois compartilham. (máx. 120) |
| `space_id` | integer | não |  |
| `month` | string | não | Quitar a dívida de um mês específico (YYYY-MM). Omitido: a dívida acumulada. (padrão `^\d{4}-(0[1-9]|1[0-2])$`) |
| `date` | data `YYYY-MM-DD` | não | Dia do pagamento. Omitido = agora. |
| `account` | string | não | Sua conta de onde saiu o dinheiro (só com i_paid_them). (máx. 120) |
| `account_id` | integer | não |  |
| `note` | string | não | máx. 2000 |

**Saída (`structuredContent`)**: `id`, `space`, `payer`, `receiver`, `amount`, `currency`, `month`, `date`, `note`, `account`, `replayed`

Exemplo:

```json
{"idempotency_key": "e1f2a3b4-0001", "person": "João", "direction": "they_paid_me", "amount": "45.00"}
```

### `settlements_delete` — Desfazer acerto

- **Classe:** Destrutiva · **Escopo:** `settlements.write` · **Custo:** 3 unidade(s)
- **Annotations:** readOnlyHint=false, destructiveHint=true, idempotentHint=true, openWorldHint=false

Desfaz um acerto registrado por engano (a dívida volta a existir).

Use quando: o usuário disser que um acerto foi lançado errado. Pegue o id em debts_summary (histórico de acertos) e confirme com o usuário qual é antes.

Não use quando: o acerto estiver certo e a pessoa só quiser ver o saldo (debts_summary). Num espaço em que você é `member`, só dá para desfazer acertos que você registrou.

**Entrada**

| Parâmetro | Tipo | Obrigatório | Descrição |
|---|---|---|---|
| `settlement_id` | integer | sim |  |

**Saída (`structuredContent`)**: `deleted`

Exemplo:

```json
{"settlement_id": 31}
```

### `recurring_create` — Criar despesa recorrente

- **Classe:** Escrita · **Escopo:** `planning.write` · **Custo:** 3 unidade(s)
- **Annotations:** readOnlyHint=false, destructiveHint=false, idempotentHint=true, openWorldHint=false
- **Idempotência:** `idempotency_key` obrigatória (replay devolve o mesmo resultado; outra carga com a mesma chave = `CONFLICT`).

Cria uma despesa que se repete (aluguel, assinatura, academia): o app lança cada ocorrência sozinho, com a mesma divisão, categoria e cartão.

Use quando: o usuário disser "todo mês pago R$ 49,90 de streaming no Nubank", "o aluguel de R$ 2.000 vence dia 5, metade do João".

Não use quando: for uma compra parcelada (transactions_create com installments) ou uma despesa única. Renda recorrente é cadastrada no app.

Mensal por padrão; `interval` = a cada N períodos; fim por data ou por nº de ocorrências.

**Entrada**

| Parâmetro | Tipo | Obrigatório | Descrição |
|---|---|---|---|
| `idempotency_key` | string | sim | Identificador ÚNICO desta intenção do usuário (ex.: um UUID novo). Repita a MESMA chave só ao reenviar exatamente a mesma chamada após erro de rede ou timeout — assim nada é criado em dobro. Pedido novo = chave nova. (mín. 8, máx. 100, padrão `^[A-Za-z0-9._:-]+$`) |
| `title` | string | sim | mín. 1, máx. 200 |
| `amount` | string | sim | Valor de cada ocorrência. (padrão `^\d{1,16}([.,]\d{1,2})?$`) |
| `space` | string | não | máx. 120 |
| `space_id` | integer | não |  |
| `currency` | string | não | padrão `^[A-Za-z]{3}$` |
| `materialize` | `past` \| `current` \| `future` | não | Com início no passado: `past` lança também as ocorrências passadas; `current` a partir do mês atual; `future` só as próximas. |
| `frequency` | `daily` \| `weekly` \| `monthly` \| `yearly` | não |  |
| `interval` | integer | não | A cada N períodos (1 = todo período). (≥ 1, ≤ 60) |
| `day_of_month` | integer | não | Dia do mês (mensal/anual). (≥ 1, ≤ 31) |
| `day_of_week` | integer | não | Dia da semana (semanal): 0 = segunda … 6 = domingo. (≥ 0, ≤ 6) |
| `month_of_year` | integer | não | Mês do ano (anual). (≥ 1, ≤ 12) |
| `start_date` | data `YYYY-MM-DD` | não | Primeira ocorrência a partir de. |
| `end_date` | data `YYYY-MM-DD` | não | Última data possível (use isto OU end_after_occurrences). |
| `end_after_occurrences` | integer | não | Termina depois de N ocorrências. (≥ 1, ≤ 600) |
| `category` | string | não | máx. 120 |
| `category_id` | integer | não |  |
| `card` | string | não | Cartão seu em que a cobrança cai. (máx. 120) |
| `card_id` | integer | não |  |
| `payment_method` | `credit_card` \| `debit_card` \| `pix` \| `cash` \| `bank_transfer` \| `boleto` \| `other` | não |  |
| `auto_settle` | boolean | não | Débito automático: cada ocorrência já nasce paga. |
| `statement_shift` | integer | não | ≥ -1, ≤ 2 |
| `description` | string | não | máx. 2000 |
| `paid_by` | string | não | Quem pagou (nome de um membro do espaço). Omitido = você. (máx. 120) |
| `paid_by_id` | integer | não |  |
| `account` | string | não | Conta de onde saiu o dinheiro (só quando quem pagou foi você; não use para cartão). (máx. 120) |
| `account_id` | integer | não |  |
| `split_with` | lista de string | não | Divide em partes IGUAIS entre você e estas pessoas (nomes de membros do espaço). Ex.: ["João"] = metade sua, metade do João. (máx. 20) |
| `split_with_ids` | lista de integer | não | máx. 20 |
| `split` | lista de objeto | não | Divisão desigual: a parte de CADA participante (inclua você, se tiver parte). Todas por valor (somando o total) ou todas por percentual (somando 100). (mín. 1, máx. 20) |

**Saída (`structuredContent`)**: `recurring`, `previous`, `changed`, `replayed`

Exemplo:

```json
{"idempotency_key": "f1a2b3c4-0001", "title": "Streaming", "amount": "49.90", "card": "Nubank", "day_of_month": 12}
```

Exemplo:

```json
{"idempotency_key": "f1a2b3c4-0002", "title": "Aluguel", "amount": "2000.00", "day_of_month": 5, "split_with": ["João"], "payment_method": "pix"}
```

### `recurring_update` — Editar despesa recorrente

- **Classe:** Escrita · **Escopo:** `planning.write` · **Custo:** 3 unidade(s)
- **Annotations:** readOnlyHint=false, destructiveHint=true, idempotentHint=true, openWorldHint=false

Altera uma despesa recorrente: valor, dia, frequência, fim, categoria, cartão, divisão, ou pausa/retoma (`active`). Ocorrências já pagas nunca mudam; as não pagas seguem `apply_to`.

Use quando: "o streaming subiu para R$ 55", "pare de lançar a academia", "o aluguel agora vence dia 10". Pegue o id em recurring_list.

Não use quando: quiser mudar uma única ocorrência (transactions_update nela).

**Entrada**

| Parâmetro | Tipo | Obrigatório | Descrição |
|---|---|---|---|
| `recurring_id` | integer | sim |  |
| `title` | string | não | mín. 1, máx. 200 |
| `amount` | string | não | Valor em string decimal com ponto e até 2 casas, ex.: "89.90". (padrão `^\d{1,16}([.,]\d{1,2})?$`) |
| `active` | boolean | não | false = pausar (para de lançar); true = retomar. |
| `remove_card` | boolean | não | true = a cobrança deixa de ser no cartão. |
| `remove_category` | boolean | não |  |
| `apply_to` | `none` \| `future` \| `all` | não | O que acontece com ocorrências JÁ lançadas e ainda não pagas: `future` (padrão) ajusta as futuras; `all` ajusta todas as não pagas; `none` só muda daqui para frente. |
| `frequency` | `daily` \| `weekly` \| `monthly` \| `yearly` | não |  |
| `interval` | integer | não | A cada N períodos (1 = todo período). (≥ 1, ≤ 60) |
| `day_of_month` | integer | não | Dia do mês (mensal/anual). (≥ 1, ≤ 31) |
| `day_of_week` | integer | não | Dia da semana (semanal): 0 = segunda … 6 = domingo. (≥ 0, ≤ 6) |
| `month_of_year` | integer | não | Mês do ano (anual). (≥ 1, ≤ 12) |
| `start_date` | data `YYYY-MM-DD` | não | Primeira ocorrência a partir de. |
| `end_date` | data `YYYY-MM-DD` | não | Última data possível (use isto OU end_after_occurrences). |
| `end_after_occurrences` | integer | não | Termina depois de N ocorrências. (≥ 1, ≤ 600) |
| `category` | string | não | máx. 120 |
| `category_id` | integer | não |  |
| `card` | string | não | Cartão seu em que a cobrança cai. (máx. 120) |
| `card_id` | integer | não |  |
| `payment_method` | `credit_card` \| `debit_card` \| `pix` \| `cash` \| `bank_transfer` \| `boleto` \| `other` | não |  |
| `auto_settle` | boolean | não | Débito automático: cada ocorrência já nasce paga. |
| `statement_shift` | integer | não | ≥ -1, ≤ 2 |
| `description` | string | não | máx. 2000 |
| `paid_by` | string | não | Quem pagou (nome de um membro do espaço). Omitido = você. (máx. 120) |
| `paid_by_id` | integer | não |  |
| `account` | string | não | Conta de onde saiu o dinheiro (só quando quem pagou foi você; não use para cartão). (máx. 120) |
| `account_id` | integer | não |  |
| `split_with` | lista de string | não | Divide em partes IGUAIS entre você e estas pessoas (nomes de membros do espaço). Ex.: ["João"] = metade sua, metade do João. (máx. 20) |
| `split_with_ids` | lista de integer | não | máx. 20 |
| `split` | lista de objeto | não | Divisão desigual: a parte de CADA participante (inclua você, se tiver parte). Todas por valor (somando o total) ou todas por percentual (somando 100). (mín. 1, máx. 20) |

**Saída (`structuredContent`)**: `recurring`, `previous`, `changed`, `replayed`

Exemplo:

```json
{"recurring_id": 7, "amount": "55.00"}
```

Exemplo:

```json
{"recurring_id": 7, "active": false}
```

### `budgets_set` — Definir meta do mês

- **Classe:** Escrita · **Escopo:** `planning.write` · **Custo:** 3 unidade(s)
- **Annotations:** readOnlyHint=false, destructiveHint=true, idempotentHint=true, openWorldHint=false

Cria ou atualiza a meta de gasto (orçamento) de uma categoria num mês. Chamar de novo com o mesmo espaço/categoria/mês/escopo só atualiza o valor.

Use quando: "quero gastar no máximo R$ 800 com mercado este mês".

Não use quando: quiser ver as metas e o quanto já foi gasto (budgets_list).

**Entrada**

| Parâmetro | Tipo | Obrigatório | Descrição |
|---|---|---|---|
| `space` | string | não | máx. 120 |
| `space_id` | integer | não |  |
| `category` | string | não | Categoria da meta (existente no espaço). (máx. 120) |
| `category_id` | integer | não |  |
| `amount` | string | sim | Quanto se pretende gastar no mês nessa categoria. (padrão `^\d{1,16}([.,]\d{1,2})?$`) |
| `month` | string | não | Mês da meta (YYYY-MM). Omitido = mês atual. (padrão `^\d{4}-(0[1-9]|1[0-2])$`) |
| `scope` | `personal` \| `space` | não | `personal` = sua meta (compara com a SUA parte); `space` = meta da casa (total do espaço). Obrigatório em espaço com mais de uma pessoa. |
| `note` | string | não | máx. 2000 |

**Saída (`structuredContent`)**: `id`, `space`, `category`, `month`, `scope`, `amount`, `created`, `app_url`

Exemplo:

```json
{"category": "Mercado", "amount": "800.00", "scope": "personal"}
```

### `categories_create` — Criar categoria

- **Classe:** Escrita · **Escopo:** `planning.write` · **Custo:** 3 unidade(s)
- **Annotations:** readOnlyHint=false, destructiveHint=false, idempotentHint=true, openWorldHint=false

Cria uma categoria nova num espaço. Se já existir uma com o mesmo nome (ignorando acento e maiúsculas), devolve ALREADY_EXISTS com o id dela — use a existente.

Use quando: o usuário pedir uma categoria que não existe (confira antes com categories_list).

Não use quando: a categoria já existir, mesmo escrita diferente.

**Entrada**

| Parâmetro | Tipo | Obrigatório | Descrição |
|---|---|---|---|
| `space` | string | não | máx. 120 |
| `space_id` | integer | não |  |
| `name` | string | sim | mín. 1, máx. 120 |
| `color` | string | não | Cor em hex, ex.: #22C55E. (padrão `^#[0-9A-Fa-f]{6}$`) |

**Saída (`structuredContent`)**: `id`, `name`, `space`

Exemplo:

```json
{"name": "Pets", "space": "Casa"}
```
