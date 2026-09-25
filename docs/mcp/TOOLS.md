# Tools do servidor MCP

<!-- GERADO por `python -m app.mcp.docs` a partir de `backend/app/mcp/registry.py`. Não edite à mão. -->

Servidor `controle-financeiro` versão `1.4.0` · 58 tools · endpoint `/mcp` (Streamable HTTP).

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
| [`transactions_history`](#transactions_history--histórico-do-lançamento) | Histórico do lançamento | Leitura | `finance.read` |
| [`statements_get`](#statements_get--ver-fatura-do-cartão) | Ver fatura do cartão | Leitura | `finance.read` |
| [`statements_show`](#statements_show--mostrar-fatura-na-conversa) | Mostrar fatura na conversa | Leitura | `finance.read` |
| [`reports_summary`](#reports_summary--resumo-financeiro-do-mês) | Resumo financeiro do mês | Leitura | `finance.read` |
| [`reports_show`](#reports_show--mostrar-resumo-do-mês-na-conversa) | Mostrar resumo do mês na conversa | Leitura | `finance.read` |
| [`budgets_list`](#budgets_list--orçamentos-do-mês) | Orçamentos do mês | Leitura | `finance.read` |
| [`reports_breakdown`](#reports_breakdown--gastos-agrupados) | Gastos agrupados | Leitura | `finance.read` |
| [`debts_summary`](#debts_summary--quem-deve-a-quem) | Quem deve a quem | Leitura | `finance.read` |
| [`payables_list`](#payables_list--contas-a-pagar) | Contas a pagar | Leitura | `finance.read` |
| [`income_list`](#income_list--rendas-do-mês) | Rendas do mês | Leitura | `finance.read` |
| [`recurring_list`](#recurring_list--despesas-e-rendas-recorrentes) | Despesas e rendas recorrentes | Leitura | `finance.read` |
| [`recurring_get`](#recurring_get--ver-recorrência) | Ver recorrência | Leitura | `finance.read` |
| [`accounts_statement`](#accounts_statement--extrato-da-conta) | Extrato da conta | Leitura | `finance.read` |
| [`transfers_list`](#transfers_list--transferências-entre-contas) | Transferências entre contas | Leitura | `finance.read` |
| [`financings_list`](#financings_list--financiamentos) | Financiamentos | Leitura | `finance.read` |
| [`financings_installment`](#financings_installment--pagardesfazer-parcela) | Pagar/desfazer parcela | Escrita | `accounts.write` |
| [`view_show`](#view_show--mostrar-na-conversa) | Mostrar na conversa | Leitura | `finance.read` |
| [`transactions_create`](#transactions_create--registrar-despesa) | Registrar despesa | Escrita | `transactions.write` |
| [`transactions_update`](#transactions_update--editar-lançamento) | Editar lançamento | Escrita | `transactions.write` |
| [`transactions_delete`](#transactions_delete--excluir-lançamento) | Excluir lançamento | Destrutiva | `transactions.write` |
| [`transactions_restore`](#transactions_restore--restaurar-lançamento-excluído) | Restaurar lançamento excluído | Escrita | `transactions.write` |
| [`transactions_bulk_preview`](#transactions_bulk_preview--prévia-de-ação-em-massa) | Prévia de ação em massa | Leitura | `finance.read` |
| [`transactions_bulk_delete`](#transactions_bulk_delete--excluir-em-massa-confirmado) | Excluir em massa (confirmado) | Destrutiva | `transactions.write` |
| [`transactions_bulk_categorize`](#transactions_bulk_categorize--categorizar-em-massa-confirmado) | Categorizar em massa (confirmado) | Escrita | `transactions.write` |
| [`transactions_bulk_update`](#transactions_bulk_update--alterar-em-massa-confirmado) | Alterar em massa (confirmado) | Escrita | `transactions.write` |
| [`imports_preview`](#imports_preview--conferir-linhas-de-extrato) | Conferir linhas de extrato | Leitura | `finance.read` |
| [`imports_commit`](#imports_commit--importar-linhas-de-extrato) | Importar linhas de extrato | Escrita | `transactions.write` |
| [`imports_list`](#imports_list--importações-feitas) | Importações feitas | Leitura | `finance.read` |
| [`statements_pay`](#statements_pay--pagar-fatura-do-cartão) | Pagar fatura do cartão | Escrita | `accounts.write` |
| [`transfers_create`](#transfers_create--transferir-entre-contas) | Transferir entre contas | Escrita | `accounts.write` |
| [`accounts_adjust_balance`](#accounts_adjust_balance--conciliar-saldo-da-conta) | Conciliar saldo da conta | Escrita | `accounts.write` |
| [`transfers_delete`](#transfers_delete--desfazer-transferência) | Desfazer transferência | Destrutiva | `accounts.write` |
| [`statements_reopen`](#statements_reopen--estornar-pagamento-de-fatura) | Estornar pagamento de fatura | Destrutiva | `accounts.write` |
| [`income_create`](#income_create--registrar-renda) | Registrar renda | Escrita | `income.write` |
| [`income_update`](#income_update--atualizar-renda) | Atualizar renda | Escrita | `income.write` |
| [`income_delete`](#income_delete--excluir-renda) | Excluir renda | Destrutiva | `income.write` |
| [`income_restore`](#income_restore--restaurar-renda-excluída) | Restaurar renda excluída | Escrita | `income.write` |
| [`settlements_create`](#settlements_create--registrar-acerto-entre-pessoas) | Registrar acerto entre pessoas | Escrita | `settlements.write` |
| [`settlements_delete`](#settlements_delete--desfazer-acerto) | Desfazer acerto | Destrutiva | `settlements.write` |
| [`recurring_create`](#recurring_create--criar-recorrência) | Criar recorrência | Escrita | `planning.write` |
| [`recurring_update`](#recurring_update--editar-recorrência) | Editar recorrência | Escrita | `planning.write` |
| [`recurring_delete`](#recurring_delete--excluir-recorrência) | Excluir recorrência | Destrutiva | `planning.write` |
| [`budgets_set`](#budgets_set--definir-meta-do-mês) | Definir meta do mês | Escrita | `planning.write` |
| [`categories_create`](#categories_create--criar-categoria-ou-tag) | Criar categoria ou tag | Escrita | `planning.write` |
| [`categories_update`](#categories_update--renomear-ou-excluir-categoriatag) | Renomear ou excluir categoria/tag | Escrita | `planning.write` |
| [`attachments_upload_link`](#attachments_upload_link--link-para-anexar-arquivo) | Link para anexar arquivo | Escrita | `transactions.write` |
| [`attachments_get`](#attachments_get--ler-anexo-recibo) | Ler anexo (recibo) | Leitura | `finance.read` |
| [`attachments_delete`](#attachments_delete--excluir-anexo) | Excluir anexo | Destrutiva | `transactions.write` |
| [`attachments_add`](#attachments_add--anexar-arquivo-da-conversa) | Anexar arquivo da conversa | Escrita | `transactions.write` |

## Referência

### `profile_get` — Conta conectada

- **Classe:** Leitura · **Escopo:** `finance.read` · **Custo:** 1 unidade(s)
- **Annotations:** readOnlyHint=true, destructiveHint=false, idempotentHint=true, openWorldHint=false

Mostra qual conta do Controle Financeiro está conectada, as permissões desta conexão, o fuso horário e a data de HOJE da conta.

Use quando: no início da conversa, para saber a data de hoje antes de interpretar 'hoje/ontem/este mês', ou quando o usuário perguntar qual conta está conectada.

Não use quando: precisar de dados financeiros — use as tools de consulta.

**Entrada**

_Sem parâmetros._

**Saída (`structuredContent`)**: `id`, `name`, `email`, `nickname`, `environment`, `timezone`, `today`, `report_currency`, `app_url`, `connection`, `server_version`, `capabilities`

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
| `min_amount` | string | não | Decimal em texto, até 2 casas. Ex.: "89.90". (padrão `^\d{1,16}([.,]\d{1,2})?$`) |
| `max_amount` | string | não | Decimal em texto, até 2 casas. Ex.: "89.90". (padrão `^\d{1,16}([.,]\d{1,2})?$`) |
| `installment_group_id` | string | não | Parcelas de uma mesma compra. (máx. 64) |
| `import_batch_id` | integer | não | Só o que entrou por uma importação (imports_list). (≥ 1) |
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
- **UI (MCP Apps):** `ui://controle-financeiro/widget-v4.html`

Desenha UM lançamento como cartão visual na conversa (valor, divisão, sua parte, cartão/fatura, parcelas) e devolve os mesmos dados de transactions_get.

Use quando: o usuário pedir para VER ou MOSTRAR um lançamento, ou quiser conferir visualmente o que acabou de ser registrado ou editado. Chame uma vez, no fim.

Não use quando: precisar dos dados para responder, analisar ou editar (transactions_get): cada chamada desenha um componente novo na conversa.

**Entrada**

| Parâmetro | Tipo | Obrigatório | Descrição |
|---|---|---|---|
| `transaction_id` | integer | sim | ≥ 1 |

**Saída (`structuredContent`)**: `transaction`

### `transactions_history` — Histórico do lançamento

- **Classe:** Leitura · **Escopo:** `finance.read` · **Custo:** 2 unidade(s)
- **Annotations:** readOnlyHint=true, destructiveHint=false, idempotentHint=true, openWorldHint=false

Mostra o que mudou num lançamento ao longo do tempo: quando, quem (e se foi via IA) e cada campo antes → depois (valor, data, título, categoria da fatura, situação, cartão…). Mudanças só de divisão, itens ou tags aparecem marcadas, sem o antes/depois.

Use quando: 'quem mudou essa despesa?', 'qual era o valor antes?', 'quando isso foi marcado como pago?'.

Não use quando: quiser o estado atual (transactions_get).

**Entrada**

| Parâmetro | Tipo | Obrigatório | Descrição |
|---|---|---|---|
| `transaction_id` | integer | sim | ≥ 1 |
| `limit` | integer | não | ≥ 1, ≤ 50 |

**Saída (`structuredContent`)**: `transaction_id`, `entries`

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

**Saída (`structuredContent`)**: `card`, `currency`, `month`, `exists`, `status`, `closing_date`, `due_date`, `total`, `paid`, `balance`, `overdue`, `purchases_count`, `purchases`, `next_cursor`, `by_category`, `payments`, `available_months`, `app_url`

### `statements_show` — Mostrar fatura na conversa

- **Classe:** Leitura · **Escopo:** `finance.read` · **Custo:** 2 unidade(s)
- **Annotations:** readOnlyHint=true, destructiveHint=false, idempotentHint=true, openWorldHint=false
- **UI (MCP Apps):** `ui://controle-financeiro/widget-v4.html`

Desenha a fatura de um cartão como componente visual na conversa (total, saldo, vencimento, as maiores categorias e as compras mais recentes) e devolve os mesmos dados de statements_get, só com a primeira página de compras.

Use quando: o usuário pedir para ver ou mostrar a fatura ('mostre minha fatura do Nubank'). Chame uma vez, com a fatura final.

Não use quando: precisar dos números para analisar, somar ou comparar (statements_get): cada chamada desenha um componente novo na conversa.

**Entrada**

| Parâmetro | Tipo | Obrigatório | Descrição |
|---|---|---|---|
| `card` | string | não | Nome do cartão. Omitido: seu único cartão. (máx. 120) |
| `card_id` | integer | não |  |
| `month` | string | não | Mês da fatura (YYYY-MM). Omitido: a fatura do ciclo atual. (padrão `^\d{4}-(0[1-9]|1[0-2])$`) |

**Saída (`structuredContent`)**: `card`, `currency`, `month`, `exists`, `status`, `closing_date`, `due_date`, `total`, `paid`, `balance`, `overdue`, `purchases_count`, `purchases`, `next_cursor`, `by_category`, `payments`, `available_months`, `app_url`

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
- **UI (MCP Apps):** `ui://controle-financeiro/widget-v4.html`

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

### `reports_breakdown` — Gastos agrupados

- **Classe:** Leitura · **Escopo:** `finance.read` · **Custo:** 3 unidade(s)
- **Annotations:** readOnlyHint=true, destructiveHint=false, idempotentHint=true, openWorldHint=false

Soma os gastos do filtro por um eixo — categoria, tag, pessoa, cartão, conta, forma de pagamento, mês, espaço ou título (≈ estabelecimento) — direto do banco, com a sua parte ou o valor cheio. Aceita os mesmos filtros de transactions_search (período, texto, cartão, categoria, pessoa…).

Use quando: 'quanto gastei em cada mercado nos últimos 6 meses?', 'quanto foi em cada cartão este ano?', 'quanto a Maria consumiu da casa?', séries por mês de uma categoria.

Não use quando: quiser o resumo pronto do mês (reports_summary) ou os lançamentos um a um (transactions_search). Não pagine a busca para somar: use esta tool.

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
| `min_amount` | string | não | Decimal em texto, até 2 casas. Ex.: "89.90". (padrão `^\d{1,16}([.,]\d{1,2})?$`) |
| `max_amount` | string | não | Decimal em texto, até 2 casas. Ex.: "89.90". (padrão `^\d{1,16}([.,]\d{1,2})?$`) |
| `installment_group_id` | string | não | Parcelas de uma mesma compra. (máx. 64) |
| `import_batch_id` | integer | não | Só o que entrou por uma importação (imports_list). (≥ 1) |
| `group_by` | `category` \| `tag` \| `person` \| `card` \| `account` \| `payment_method` \| `month` \| `space` \| `title` | sim | Eixo: category, tag, person (quanto cabe a CADA pessoa), card, account (conta de onde saiu), payment_method, month (competência), space, title (título normalizado: aproxima o estabelecimento). |
| `basis` | `my_share` \| `total` | não | my_share = a SUA parte (padrão); total = o valor cheio dos lançamentos. |
| `limit` | integer | não | Grupos por moeda; o resto vem somado em `others`. (≥ 1, ≤ 50) |

**Saída (`structuredContent`)**: `group_by`, `basis`, `groups`, `others`, `totals`, `resolved`

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

Lista suas rendas (salário, freelas, reembolsos) do mês, com situação: prevista, recebida, atrasada ou cancelada, a conta e a recorrência de origem. Com `income_id`, devolve só aquela renda (de qualquer mês).

Use quando: 'meu salário caiu?', 'quanto vou receber este mês?', ou antes de editar uma renda.

Não use quando: quiser registrar ou marcar renda como recebida (income_create / income_update).

**Entrada**

| Parâmetro | Tipo | Obrigatório | Descrição |
|---|---|---|---|
| `month` | string | não | Competência (YYYY-MM). Omitido: o mês atual. (padrão `^\d{4}-(0[1-9]|1[0-2])$`) |
| `status` | `expected` \| `received` \| `overdue` \| `cancelled` | não |  |
| `income_id` | integer | não | Uma renda específica, de qualquer mês. (≥ 1) |

**Saída (`structuredContent`)**: `month`, `currency_totals`, `incomes`

### `recurring_list` — Despesas e rendas recorrentes

- **Classe:** Leitura · **Escopo:** `finance.read` · **Custo:** 1 unidade(s)
- **Annotations:** readOnlyHint=true, destructiveHint=false, idempotentHint=true, openWorldHint=false

Lista suas despesas recorrentes (aluguel, assinaturas, contas fixas) por espaço e suas rendas recorrentes (salário): valor cheio, a SUA parte, divisão, quem paga, cartão/conta, próxima ocorrência e se ainda estão ativas.

Use quando: 'quais são minhas assinaturas?', 'quanto pago de contas fixas?', ou antes de editar uma recorrência (recurring_update precisa do id).

Não use quando: quiser os lançamentos já gerados (transactions_search).

**Entrada**

| Parâmetro | Tipo | Obrigatório | Descrição |
|---|---|---|---|
| `space` | string | não | máx. 120 |
| `space_id` | integer | não |  |
| `kind` | `all` \| `expense` \| `income` | não |  |
| `active_only` | boolean | não |  |

**Saída (`structuredContent`)**: `items`, `monthly_my_share`

### `recurring_get` — Ver recorrência

- **Classe:** Leitura · **Escopo:** `finance.read` · **Custo:** 1 unidade(s)
- **Annotations:** readOnlyHint=true, destructiveHint=false, idempotentHint=true, openWorldHint=false

Devolve UMA recorrência completa pelo id: valor, a sua parte, a divisão de cada ocorrência, quem paga, forma de pagamento, cartão/conta, categoria, início/fim e as próximas datas.

Use quando: precisar do estado inteiro antes de editar (recurring_update) ou para explicar quanto uma assinatura dividida custa para o usuário.

Não use quando: quiser a lista (recurring_list).

**Entrada**

| Parâmetro | Tipo | Obrigatório | Descrição |
|---|---|---|---|
| `recurring_id` | integer | sim | ≥ 1 |
| `kind` | `expense` \| `income` | não | expense = despesa recorrente; income = renda recorrente. |

**Saída (`structuredContent`)**: `recurring`, `upcoming`

### `accounts_statement` — Extrato da conta

- **Classe:** Leitura · **Escopo:** `finance.read` · **Custo:** 2 unidade(s)
- **Annotations:** readOnlyHint=true, destructiveHint=false, idempotentHint=true, openWorldHint=false

Explica o saldo: com `account`, o extrato daquela conta com o SALDO CORRENTE linha a linha (despesas, rendas, pagamentos de fatura, acertos, transferências, ajustes); sem conta, o caixa do mês (tudo que entrou e saiu, em todas as contas). Paginado, mais recentes primeiro.

Use quando: 'por que meu saldo no Itaú é esse?', 'o que saiu da conta este mês?', conciliar com o extrato do banco.

Não use quando: quiser só os saldos atuais (accounts_list) ou só despesas com filtros (transactions_search).

**Entrada**

| Parâmetro | Tipo | Obrigatório | Descrição |
|---|---|---|---|
| `account` | string | não | Conta (nome). Omitida: o caixa do mês, de todas as contas. (máx. 120) |
| `account_id` | integer | não |  |
| `month` | string | não | Mês (YYYY-MM). Omitido: conta = o extrato inteiro; caixa = o mês atual. (padrão `^\d{4}-(0[1-9]|1[0-2])$`) |
| `sources` | lista de `transaction` \| `statement_payment` \| `settlement_sent` \| `settlement_received` \| `financing_installment` \| `income` | não | Só no caixa do mês: filtra as origens. (máx. 6) |
| `limit` | integer | não | ≥ 1, ≤ 100 |
| `cursor` | string | não | `next_cursor` da página anterior. (máx. 512) |

**Saída (`structuredContent`)**: `mode`, `account`, `month`, `currency`, `opening_amount`, `opening_on`, `balance`, `cash_in`, `cash_out`, `net_cash`, `entries`, `total_count`, `next_cursor`, `app_url`

### `transfers_list` — Transferências entre contas

- **Classe:** Leitura · **Escopo:** `finance.read` · **Custo:** 1 unidade(s)
- **Annotations:** readOnlyHint=true, destructiveHint=false, idempotentHint=true, openWorldHint=false

Lista as transferências entre as suas contas (mais recentes primeiro), com o id de cada uma.

Use quando: 'qual transferência fiz ontem?', ou antes de desfazer uma (transfers_delete).

Não use quando: quiser o extrato completo de uma conta (accounts_statement).

**Entrada**

| Parâmetro | Tipo | Obrigatório | Descrição |
|---|---|---|---|
| `month` | string | não | Só as do mês (YYYY-MM). Omitido: as mais recentes. (padrão `^\d{4}-(0[1-9]|1[0-2])$`) |
| `account` | string | não | Só as que envolvem esta conta. (máx. 120) |
| `account_id` | integer | não |  |
| `limit` | integer | não | ≥ 1, ≤ 100 |

**Saída (`structuredContent`)**: `transfers`

### `financings_list` — Financiamentos

- **Classe:** Leitura · **Escopo:** `finance.read` · **Custo:** 2 unidade(s)
- **Annotations:** readOnlyHint=true, destructiveHint=false, idempotentHint=true, openWorldHint=false

Lista seus financiamentos (casa, carro) com saldo devedor, parcelas pagas e restantes, a próxima parcela e atrasos. Com `financing`, traz também o cronograma (principal, juros, saldo depois de cada parcela, paga ou não), paginado.

Use quando: 'quanto falta do financiamento?', 'qual a próxima parcela?', antes de pagar ou desfazer uma parcela (financings_installment).

Não use quando: quiser tudo que vence no mês, de todas as origens (payables_list).

**Entrada**

| Parâmetro | Tipo | Obrigatório | Descrição |
|---|---|---|---|
| `financing` | string | não | Um financiamento (nome): devolve também o cronograma. (máx. 120) |
| `financing_id` | integer | não |  |
| `limit` | integer | não | Parcelas do cronograma por página. (≥ 1, ≤ 120) |
| `cursor` | string | não | máx. 512 |

**Saída (`structuredContent`)**: `financings`, `schedule`, `next_cursor`

### `financings_installment` — Pagar/desfazer parcela

- **Classe:** Escrita · **Escopo:** `accounts.write` · **Custo:** 3 unidade(s)
- **Annotations:** readOnlyHint=false, destructiveHint=true, idempotentHint=true, openWorldHint=false
- **UI (MCP Apps):** `ui://controle-financeiro/widget-v4.html` · chamável pelo componente

Marca uma parcela de financiamento como paga (`action=pay`, na conta e na data informadas; com `space`, lança também a despesa naquele espaço) ou desfaz o pagamento (`action=unpay`: a parcela volta a aberta e a despesa lançada some).

Use quando: 'paguei a parcela do carro', 'marquei a parcela errada, desfaça'.

Não use quando: quiser cadastrar, alterar ou quitar o contrato inteiro (isso é no app).

**Entrada**

| Parâmetro | Tipo | Obrigatório | Descrição |
|---|---|---|---|
| `action` | `pay` \| `unpay` | sim | pay = paguei a parcela; unpay = desfazer (marquei errado). |
| `financing` | string | não | máx. 120 |
| `financing_id` | integer | não |  |
| `installment` | integer | não | Número da parcela. Omitido: pay = a próxima em aberto; unpay = a última paga. (≥ 1, ≤ 600) |
| `account` | string | não | pay: conta de onde saiu o dinheiro. (máx. 120) |
| `account_id` | integer | não |  |
| `paid_on` | data `YYYY-MM-DD` | não | pay: dia do pagamento. Omitido = hoje. |
| `space` | string | não | pay: lança também a despesa neste espaço (para dividir). Omitido = só marca como paga. (máx. 120) |
| `space_id` | integer | não |  |

**Saída (`structuredContent`)**: `financing`, `installment`, `action`, `transaction_id`

Exemplo:

```json
{"action": "pay", "financing": "Carro", "account": "Itaú"}
```

Exemplo:

```json
{"action": "unpay", "financing": "Carro", "installment": 12}
```

### `view_show` — Mostrar na conversa

- **Classe:** Leitura · **Escopo:** `finance.read` · **Custo:** 2 unidade(s)
- **Annotations:** readOnlyHint=true, destructiveHint=false, idempotentHint=true, openWorldHint=false
- **UI (MCP Apps):** `ui://controle-financeiro/widget-v4.html`

Desenha uma tela na conversa, com os mesmos números da tool de dados: lista de lançamentos filtrada (paginável, com edição), gastos agrupados, extrato de conta, caixa do mês, dívidas, a pagar, metas, recorrências, rendas, financiamento, histórico de um lançamento ou importações.

Use quando: o usuário pedir para VER ou MOSTRAR uma dessas telas. Chame uma vez, no fim.

Não use quando: precisar dos dados para responder ou analisar (use a tool de dados): cada chamada desenha um componente novo na conversa. Um lançamento: transactions_show; fatura: statements_show; resumo do mês: reports_show.

**Entrada**

| Parâmetro | Tipo | Obrigatório | Descrição |
|---|---|---|---|
| `view` | `transactions` \| `account` \| `cash` \| `breakdown` \| `debts` \| `payables` \| `budgets` \| `recurring` \| `income` \| `financing` \| `history` \| `imports` | sim | transactions (lista com filtros), breakdown (gastos agrupados), account (extrato de uma conta), cash (caixa do mês), debts, payables (a pagar), budgets (metas), recurring, income, financing, history (de um lançamento), imports. |
| `space` | string | não | máx. 120 |
| `space_id` | integer | não |  |
| `month` | string | não | Mês de competência no formato YYYY-MM. (padrão `^\d{4}-(0[1-9]|1[0-2])$`) |
| `text` | string | não | mín. 1, máx. 80 |
| `date_from` | data `YYYY-MM-DD` | não | Dia civil no fuso da conta (ver profile_get.timezone), formato YYYY-MM-DD. |
| `date_to` | data `YYYY-MM-DD` | não | Dia civil no fuso da conta (ver profile_get.timezone), formato YYYY-MM-DD. |
| `card` | string | não | máx. 120 |
| `category` | string | não | máx. 120 |
| `tag` | string | não | máx. 60 |
| `person` | string | não | máx. 120 |
| `uncategorized` | boolean | não |  |
| `settled` | boolean | não |  |
| `group_by` | `category` \| `tag` \| `person` \| `card` \| `account` \| `payment_method` \| `month` \| `space` \| `title` | não |  |
| `basis` | `my_share` \| `total` | não |  |
| `account` | string | não | máx. 120 |
| `account_id` | integer | não |  |
| `kind` | `all` \| `expense` \| `income` | não |  |
| `financing` | string | não | máx. 120 |
| `transaction_id` | integer | não | ≥ 1 |
| `batch_id` | integer | não | ≥ 1 |

**Saída (`structuredContent`)**: `view`, `source_tool`, `data`

### `transactions_create` — Registrar despesa

- **Classe:** Escrita · **Escopo:** `transactions.write` · **Custo:** 3 unidade(s)
- **Annotations:** readOnlyHint=false, destructiveHint=false, idempotentHint=true, openWorldHint=false
- **Idempotência:** `idempotency_key` obrigatória (replay devolve o mesmo resultado; outra carga com a mesma chave = `CONFLICT`).
- **UI (MCP Apps):** `ui://controle-financeiro/widget-v4.html` · chamável pelo componente

Registra uma despesa (compra, conta, gasto) numa única chamada atômica: valor, data, categoria, tags, cartão e parcelas, quem pagou, divisão com outras pessoas, conta de origem, moeda estrangeira e se já foi paga. O servidor calcula a fatura, as parcelas e os centavos da divisão — não calcule nada disso.

Use quando: o usuário disser que comprou/gastou/pagou algo ("adicione R$ 89,90 de gasolina no Nubank", "comprei uma TV de R$ 3.000 em 10x", "jantar de 120, metade do João").

Não use quando: for renda (income_create), transferência entre contas (transfers_create), pagamento de fatura (statements_pay) ou acerto de dívida entre pessoas (settlements_create); nem para corrigir um lançamento existente (transactions_update).

Espaço: informe `space` quando o usuário disser. Omitido, vale o ÚNICO espaço que tem todas as pessoas citadas (sem ninguém citado: seu espaço pessoal); se houver dúvida volta AMBIGUOUS — pergunte ao usuário. Nomes (cartão, categoria, pessoa) ambíguos também voltam AMBIGUOUS com candidatos; repita a chamada com o `*_id` escolhido e a MESMA idempotency_key.

Divisão: `split_with` = partes iguais entre você e as pessoas; `split` = partes desiguais (valor ou percentual de cada um). Sem divisão, a despesa é toda sua.

Nota com itens: `items` (cada um com categoria e divisão próprias) + `adjustments` (desconto, frete…); o servidor confere que fecham o total e rateia os centavos.

Gere uma idempotency_key nova para cada despesa e reutilize-a só ao repetir a mesma chamada.

**Entrada**

| Parâmetro | Tipo | Obrigatório | Descrição |
|---|---|---|---|
| `idempotency_key` | string | sim | Identificador ÚNICO desta intenção do usuário (ex.: um UUID novo). Repita a MESMA chave só ao reenviar exatamente a mesma chamada após erro de rede ou timeout — assim nada é criado em dobro. Pedido novo = chave nova. (mín. 8, máx. 100, padrão `^[A-Za-z0-9._:-]+$`) |
| `title` | string | sim | Descrição curta, como aparece na lista (ex.: "Gasolina"). (mín. 1, máx. 200) |
| `amount` | string | não | Valor TOTAL da compra (nas parceladas, o total, não a parcela). Com `items` pode ser omitido (= itens + ajustes); se vier, tem de fechar com eles. Ex.: "89.90". (padrão `^\d{1,16}([.,]\d{1,2})?$`) |
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
| `items` | lista de objeto | não | Itens da nota. Item sem divisão própria (owner/split_with/split) segue a do lançamento. (mín. 1, máx. 200) |
| `adjustments` | lista de objeto | não | Desconto, frete, taxa… que fecham itens com o total. (máx. 20) |

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

Exemplo:

```json
{"title": "Mercado", "card": "Nubank", "idempotency_key": "b3f1c2d4-0004", "items": [{"title": "Arroz", "amount": "30.00", "owner": "eu"}, {"title": "Shampoo", "amount": "20.00", "owner": "Maria"}, {"title": "Refrigerante", "quantity": "2", "unit_amount": "25.00", "split_with": ["Maria"]}]}
```

### `transactions_update` — Editar lançamento

- **Classe:** Escrita · **Escopo:** `transactions.write` · **Custo:** 3 unidade(s)
- **Annotations:** readOnlyHint=false, destructiveHint=true, idempotentHint=true, openWorldHint=false
- **UI (MCP Apps):** `ui://controle-financeiro/widget-v4.html` · chamável pelo componente

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
| `amount` | string | não | Novo valor total, na moeda DA COMPRA: a de `currency`, se informada; senão a original (`foreign.original_currency`) quando o lançamento foi convertido. Ex.: "89.90". (padrão `^\d{1,16}([.,]\d{1,2})?$`) |
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
| `items` | lista de objeto | não | Substitui TODOS os itens da nota (mande a lista completa). Mesmo formato de transactions_create. (mín. 1, máx. 200) |
| `adjustments` | lista de objeto | não | Substitui os ajustes (só junto com `items`; [] remove). (máx. 20) |
| `expected_version` | string | não | A `version` que você leu. Se o registro mudou desde então, a escrita volta CONFLICT (com a versão atual) em vez de sobrescrever a mudança de outra pessoa. (mín. 6, máx. 40, padrão `^[0-9a-f]+$`) |

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
- **UI (MCP Apps):** `ui://controle-financeiro/widget-v4.html` · chamável pelo componente

Exclui um lançamento (ou, com `scope=purchase`, todas as parcelas em aberto de uma compra parcelada). A exclusão pode ser desfeita com transactions_restore. Despesa paga não é excluída — reabra antes.

Use quando: o usuário pedir para apagar um lançamento específico que você já identificou (mostre qual é antes: título, data, valor).

Não use quando: forem vários lançamentos (use transactions_bulk_preview + transactions_bulk_delete) ou houver dúvida sobre qual lançamento é — pergunte.

Se o lançamento tiver anexos (recibos), eles seriam apagados para sempre: a tool recusa e pede o fluxo com prévia (transactions_bulk_preview com action=delete), que mostra isso ao usuário.

**Entrada**

| Parâmetro | Tipo | Obrigatório | Descrição |
|---|---|---|---|
| `transaction_id` | integer | sim |  |
| `scope` | `installment` \| `purchase` | não | Parcelada: `installment` exclui só esta parcela; `purchase` exclui todas as parcelas em aberto da compra. |
| `expected_version` | string | não | A `version` que você leu. Se o registro mudou desde então, a escrita volta CONFLICT (com a versão atual) em vez de sobrescrever a mudança de outra pessoa. (mín. 6, máx. 40, padrão `^[0-9a-f]+$`) |

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
- **UI (MCP Apps):** `ui://controle-financeiro/widget-v4.html` · chamável pelo componente

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
- **UI (MCP Apps):** `ui://controle-financeiro/widget-v4.html` · chamável pelo componente

Primeiro passo OBRIGATÓRIO para alterar vários lançamentos (ou excluir um com anexos): excluir, categorizar os sem categoria, trocar categoria, pôr/tirar tag, marcar como pago — ou DESFAZER UMA IMPORTAÇÃO (action=delete com filters.import_batch_id). Não altera nada: calcula o conjunto exato, o total, uma amostra e o que ficou de fora, e devolve um `confirmation_token` válido por 10 minutos.

Use quando: "apague as compras do McDonald's deste mês", "categorize tudo sem categoria de setembro como Mercado", "ponha a tag viagem nas compras de julho".

Não use quando: for um único lançamento sem anexos (transactions_delete/transactions_update).

Depois: MOSTRE count, total e amostra ao usuário e só com a confirmação dele chame a tool que `next_step` indicar (bulk_delete, bulk_categorize ou bulk_update) com o token.

**Entrada**

| Parâmetro | Tipo | Obrigatório | Descrição |
|---|---|---|---|
| `action` | `delete` \| `categorize` \| `recategorize` \| `tag` \| `untag` \| `settle` | sim | delete = excluir; categorize = pôr categoria nos SEM categoria; recategorize = trocar a categoria; tag / untag = pôr/tirar uma tag; settle = marcar como pago. |
| `transaction_ids` | lista de integer | não | Ids exatos (de transactions_search). Use isto OU `filters`. (mín. 1, máx. 200) |
| `filters` | objeto | não | Os mesmos filtros de transactions_search (ao menos um). Use isto OU `transaction_ids`. |
| `category` | string | não | Categoria a aplicar (categorize/recategorize). (máx. 120) |
| `category_id` | integer | não |  |
| `tag` | string | não | Tag a pôr ou tirar (tag/untag). (máx. 60) |

**Saída (`structuredContent`)**: `action`, `count`, `totals`, `sample`, `ineligible_count`, `ineligible`, `not_found_ids`, `attachments`, `category`, `tag`, `space`, `confirmation_token`, `expires_at`, `next_step`

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
- **UI (MCP Apps):** `ui://controle-financeiro/widget-v4.html` · chamável pelo componente

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
- **UI (MCP Apps):** `ui://controle-financeiro/widget-v4.html` · chamável pelo componente

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

### `transactions_bulk_update` — Alterar em massa (confirmado)

- **Classe:** Escrita · **Escopo:** `transactions.write` · **Custo:** 5 unidade(s)
- **Annotations:** readOnlyHint=false, destructiveHint=true, idempotentHint=true, openWorldHint=false
- **UI (MCP Apps):** `ui://controle-financeiro/widget-v4.html` · chamável pelo componente

Executa a alteração preparada por transactions_bulk_preview com action recategorize (troca a categoria), tag / untag (põe ou tira uma tag) ou settle (marca como pago). Recebe só o `confirmation_token` e altera exatamente o conjunto da prévia, tudo ou nada; se algo mudou desde a prévia, nada é alterado e é preciso nova prévia.

Use quando: o usuário CONFIRMOU a prévia que você mostrou.

Não use quando: não houver prévia confirmada; para excluir (transactions_bulk_delete) ou categorizar só os sem categoria (transactions_bulk_categorize).

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
- **UI (MCP Apps):** `ui://controle-financeiro/widget-v4.html` · chamável pelo componente

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

### `imports_list` — Importações feitas

- **Classe:** Leitura · **Escopo:** `finance.read` · **Custo:** 2 unidade(s)
- **Annotations:** readOnlyHint=true, destructiveHint=false, idempotentHint=true, openWorldHint=false

Lista os lotes de importação de extrato que VOCÊ fez (mais recentes primeiro), com quantas linhas entraram, foram ignoradas ou eram duplicadas. Com `batch_id`, traz as linhas do lote.

Use quando: 'o que entrou na importação de ontem?', ou para DESFAZER uma importação: pegue o id aqui e use transactions_bulk_preview (action=delete, import_batch_id) + transactions_bulk_delete.

Não use quando: quiser importar um extrato novo (imports_preview → imports_commit).

**Entrada**

| Parâmetro | Tipo | Obrigatório | Descrição |
|---|---|---|---|
| `batch_id` | integer | não | Um lote: devolve também as linhas. (≥ 1) |
| `limit` | integer | não | Lotes (sem batch_id) ou linhas (com batch_id) por página. (≥ 1, ≤ 100) |
| `cursor` | string | não | máx. 512 |

**Saída (`structuredContent`)**: `batches`, `rows`, `next_cursor`

### `statements_pay` — Pagar fatura do cartão

- **Classe:** Escrita · **Escopo:** `accounts.write` · **Custo:** 3 unidade(s)
- **Annotations:** readOnlyHint=false, destructiveHint=false, idempotentHint=true, openWorldHint=false
- **Idempotência:** `idempotency_key` obrigatória (replay devolve o mesmo resultado; outra carga com a mesma chave = `CONFLICT`).
- **UI (MCP Apps):** `ui://controle-financeiro/widget-v4.html` · chamável pelo componente

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
| `amount` | string | não | Valor pago. Omitido = o saldo inteiro da fatura. Ex.: "89.90". (padrão `^\d{1,16}([.,]\d{1,2})?$`) |
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
- **UI (MCP Apps):** `ui://controle-financeiro/widget-v4.html` · chamável pelo componente

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
| `amount` | string | sim | Valor que SAIU da conta de origem. Ex.: "89.90". (padrão `^\d{1,16}([.,]\d{1,2})?$`) |
| `to_amount` | string | não | Só entre moedas diferentes: quanto ENTROU no destino (o app não converte sozinho). Ex.: "89.90". (padrão `^\d{1,16}([.,]\d{1,2})?$`) |
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
- **UI (MCP Apps):** `ui://controle-financeiro/widget-v4.html` · chamável pelo componente

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

### `transfers_delete` — Desfazer transferência

- **Classe:** Destrutiva · **Escopo:** `accounts.write` · **Custo:** 3 unidade(s)
- **Annotations:** readOnlyHint=false, destructiveHint=true, idempotentHint=true, openWorldHint=false
- **UI (MCP Apps):** `ui://controle-financeiro/widget-v4.html` · chamável pelo componente

Desfaz uma transferência entre suas contas: as duas pernas (saída e entrada) somem juntas, e os saldos voltam ao que eram.

Use quando: o usuário disser que uma transferência estava errada ou foi registrada duas vezes (pegue o id em transfers_list e confirme qual).

Não use quando: quiser corrigir o valor — desfaça e registre de novo (transfers_create).

**Entrada**

| Parâmetro | Tipo | Obrigatório | Descrição |
|---|---|---|---|
| `transfer_id` | integer | sim | ≥ 1 |

**Saída (`structuredContent`)**: `deleted`

Exemplo:

```json
{"transfer_id": 5}
```

### `statements_reopen` — Estornar pagamento de fatura

- **Classe:** Destrutiva · **Escopo:** `accounts.write` · **Custo:** 3 unidade(s)
- **Annotations:** readOnlyHint=false, destructiveHint=true, idempotentHint=true, openWorldHint=false
- **UI (MCP Apps):** `ui://controle-financeiro/widget-v4.html` · chamável pelo componente

Estorna os pagamentos de uma fatura, como o botão "Reabrir" do app: os pagamentos somem, o dinheiro volta às contas e a fatura volta um passo (paga → fechada; fechada com pagamento parcial → aberta). Sem pagamento na fatura, não faz nada.

Use quando: o usuário disser que um pagamento de fatura foi registrado errado ou em dobro.

Não use quando: quiser pagar (statements_pay) ou só ver os pagamentos (statements_get).

**Entrada**

| Parâmetro | Tipo | Obrigatório | Descrição |
|---|---|---|---|
| `card` | string | não | Cartão (nome). Omitido: seu único cartão. (máx. 120) |
| `card_id` | integer | não |  |
| `month` | string | sim | Mês da fatura (YYYY-MM). (padrão `^\d{4}-(0[1-9]|1[0-2])$`) |

**Saída (`structuredContent`)**: `card`, `month`, `previous_status`, `status`, `reversed_payments`, `balance`, `currency`

Exemplo:

```json
{"card": "Nubank", "month": "2026-09"}
```

### `income_create` — Registrar renda

- **Classe:** Escrita · **Escopo:** `income.write` · **Custo:** 3 unidade(s)
- **Annotations:** readOnlyHint=false, destructiveHint=false, idempotentHint=true, openWorldHint=false
- **Idempotência:** `idempotency_key` obrigatória (replay devolve o mesmo resultado; outra carga com a mesma chave = `CONFLICT`).
- **UI (MCP Apps):** `ui://controle-financeiro/widget-v4.html` · chamável pelo componente

Registra uma entrada de dinheiro pessoal: salário, freela, reembolso, venda. Renda é sua, não de um espaço, e não se divide.

Use quando: o usuário disser que recebeu ou vai receber dinheiro ("caiu meu salário de R$ 5.000", "vou receber R$ 800 do freela dia 10").

Não use quando: alguém te pagou uma dívida de despesa dividida (settlements_create) ou foi transferência entre suas contas (transfers_create).

**Entrada**

| Parâmetro | Tipo | Obrigatório | Descrição |
|---|---|---|---|
| `idempotency_key` | string | sim | Identificador ÚNICO desta intenção do usuário (ex.: um UUID novo). Repita a MESMA chave só ao reenviar exatamente a mesma chamada após erro de rede ou timeout — assim nada é criado em dobro. Pedido novo = chave nova. (mín. 8, máx. 100, padrão `^[A-Za-z0-9._:-]+$`) |
| `title` | string | sim | Ex.: "Salário", "Freela site". (mín. 1, máx. 200) |
| `amount` | string | sim | Decimal em texto, até 2 casas. Ex.: "89.90". (padrão `^\d{1,16}([.,]\d{1,2})?$`) |
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
- **UI (MCP Apps):** `ui://controle-financeiro/widget-v4.html` · chamável pelo componente

Altera uma renda sua (valor, data, título, categoria, conta) e/ou o estado dela: recebida, prevista de novo ou cancelada. Devolve como estava antes (`previous`).

Use quando: o usuário disser "o salário caiu", "o freela atrasou, ainda não recebi", "esse pagamento não vai vir" ou pedir para corrigir uma renda. Pegue o `income_id` em income_list.

Não use quando: for registrar uma renda nova (income_create).

**Entrada**

| Parâmetro | Tipo | Obrigatório | Descrição |
|---|---|---|---|
| `income_id` | integer | sim |  |
| `title` | string | não | mín. 1, máx. 200 |
| `description` | string | não | máx. 2000 |
| `amount` | string | não | Novo valor, na moeda DA RENDA: a de `currency`, se informada; senão a original (`original_currency`) quando a renda foi convertida. Ex.: "89.90". (padrão `^\d{1,16}([.,]\d{1,2})?$`) |
| `currency` | string | não | Moeda ISO; estrangeira é reconvertida na data. (padrão `^[A-Za-z]{3}$`) |
| `date` | data `YYYY-MM-DD` | não | Nova data da renda (competência). |
| `category` | string | não | Rótulo livre da renda (ex.: "Salário", "Freela"). (máx. 60) |
| `account` | string | não | máx. 120 |
| `account_id` | integer | não |  |
| `status` | `received` \| `expected` \| `cancelled` | não | `received` = caiu na conta (use `received_on`/`account` se souber); `expected` = desfaz o "recebi"; `cancelled` = não veio e não virá (definitivo, continua visível). |
| `received_on` | data `YYYY-MM-DD` | não | Dia em que caiu (com status=received). Omitido = hoje. |
| `expected_version` | string | não | A `version` que você leu. Se o registro mudou desde então, a escrita volta CONFLICT (com a versão atual) em vez de sobrescrever a mudança de outra pessoa. (mín. 6, máx. 40, padrão `^[0-9a-f]+$`) |

**Saída (`structuredContent`)**: `income`, `previous`, `changed`

Exemplo:

```json
{"income_id": 12, "status": "received", "account": "Itaú"}
```

Exemplo:

```json
{"income_id": 12, "amount": "5200.00"}
```

### `income_delete` — Excluir renda

- **Classe:** Destrutiva · **Escopo:** `income.write` · **Custo:** 3 unidade(s)
- **Annotations:** readOnlyHint=false, destructiveHint=true, idempotentHint=true, openWorldHint=false
- **UI (MCP Apps):** `ui://controle-financeiro/widget-v4.html` · chamável pelo componente

Exclui uma renda registrada por engano (some das listas e dos totais). Dá para desfazer com income_restore.

Use quando: o usuário pedir para apagar uma renda que não devia existir.

Não use quando: a renda prevista simplesmente não veio — aí é cancelar (income_update status=cancelled), que continua visível e impede o salário do mês de ser recriado.

**Entrada**

| Parâmetro | Tipo | Obrigatório | Descrição |
|---|---|---|---|
| `income_id` | integer | sim | ≥ 1 |
| `expected_version` | string | não | A `version` que você leu. Se o registro mudou desde então, a escrita volta CONFLICT (com a versão atual) em vez de sobrescrever a mudança de outra pessoa. (mín. 6, máx. 40, padrão `^[0-9a-f]+$`) |

**Saída (`structuredContent`)**: `deleted`

Exemplo:

```json
{"income_id": 12}
```

### `income_restore` — Restaurar renda excluída

- **Classe:** Escrita · **Escopo:** `income.write` · **Custo:** 3 unidade(s)
- **Annotations:** readOnlyHint=false, destructiveHint=false, idempotentHint=true, openWorldHint=false
- **UI (MCP Apps):** `ui://controle-financeiro/widget-v4.html` · chamável pelo componente

Desfaz a exclusão de uma renda (volta às listas e aos totais).

Use quando: o usuário pedir para desfazer uma exclusão feita por income_delete.

Não use quando: a renda estiver cancelada (reative com income_update status=expected).

**Entrada**

| Parâmetro | Tipo | Obrigatório | Descrição |
|---|---|---|---|
| `income_id` | integer | sim | ≥ 1 |

**Saída (`structuredContent`)**: `income`, `replayed`

Exemplo:

```json
{"income_id": 12}
```

### `settlements_create` — Registrar acerto entre pessoas

- **Classe:** Escrita · **Escopo:** `settlements.write` · **Custo:** 3 unidade(s)
- **Annotations:** readOnlyHint=false, destructiveHint=false, idempotentHint=true, openWorldHint=false
- **Idempotência:** `idempotency_key` obrigatória (replay devolve o mesmo resultado; outra carga com a mesma chave = `CONFLICT`).
- **UI (MCP Apps):** `ui://controle-financeiro/widget-v4.html` · chamável pelo componente

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
| `amount` | string | sim | Valor pago. Não pode passar da dívida (veja debts_summary). Ex.: "89.90". (padrão `^\d{1,16}([.,]\d{1,2})?$`) |
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
- **UI (MCP Apps):** `ui://controle-financeiro/widget-v4.html` · chamável pelo componente

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

### `recurring_create` — Criar recorrência

- **Classe:** Escrita · **Escopo:** `planning.write` · **Custo:** 3 unidade(s)
- **Annotations:** readOnlyHint=false, destructiveHint=false, idempotentHint=true, openWorldHint=false
- **Idempotência:** `idempotency_key` obrigatória (replay devolve o mesmo resultado; outra carga com a mesma chave = `CONFLICT`).
- **UI (MCP Apps):** `ui://controle-financeiro/widget-v4.html` · chamável pelo componente

Cria uma despesa que se repete (aluguel, assinatura, academia) ou, com `kind=income`, uma renda que se repete (salário): o app lança cada ocorrência sozinho, com a mesma divisão, categoria e cartão (renda: a conta onde cai, em `account`).

Use quando: o usuário disser "todo mês pago R$ 49,90 de streaming no Nubank", "o aluguel de R$ 2.000 vence dia 5, metade do João", "meu salário é R$ 4.000 todo dia 5".

Não use quando: for uma compra parcelada (transactions_create com installments) ou um gasto/renda única (transactions_create / income_create).

Mensal por padrão; `interval` = a cada N períodos; fim por data ou por nº de ocorrências.

**Entrada**

| Parâmetro | Tipo | Obrigatório | Descrição |
|---|---|---|---|
| `idempotency_key` | string | sim | Identificador ÚNICO desta intenção do usuário (ex.: um UUID novo). Repita a MESMA chave só ao reenviar exatamente a mesma chamada após erro de rede ou timeout — assim nada é criado em dobro. Pedido novo = chave nova. (mín. 8, máx. 100, padrão `^[A-Za-z0-9._:-]+$`) |
| `kind` | `expense` \| `income` | não | expense = despesa que se repete; income = renda que se repete (salário). |
| `title` | string | sim | mín. 1, máx. 200 |
| `amount` | string | sim | Valor de cada ocorrência. Ex.: "89.90". (padrão `^\d{1,16}([.,]\d{1,2})?$`) |
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

Exemplo:

```json
{"idempotency_key": "f1a2b3c4-0003", "kind": "income", "title": "Salário", "amount": "4000.00", "day_of_month": 5, "account": "Itaú"}
```

### `recurring_update` — Editar recorrência

- **Classe:** Escrita · **Escopo:** `planning.write` · **Custo:** 3 unidade(s)
- **Annotations:** readOnlyHint=false, destructiveHint=true, idempotentHint=true, openWorldHint=false
- **UI (MCP Apps):** `ui://controle-financeiro/widget-v4.html` · chamável pelo componente

Altera uma despesa recorrente (ou, com `kind=income`, uma renda recorrente): valor, dia, frequência, fim, categoria, cartão, divisão, conta da renda, ou pausa/retoma (`active`). Ocorrências já pagas nunca mudam; as não pagas seguem `apply_to`.

Use quando: "o streaming subiu para R$ 55", "pare de lançar a academia", "o aluguel agora vence dia 10". Pegue o id em recurring_list.

Não use quando: quiser mudar uma única ocorrência (transactions_update nela).

**Entrada**

| Parâmetro | Tipo | Obrigatório | Descrição |
|---|---|---|---|
| `recurring_id` | integer | sim |  |
| `kind` | `expense` \| `income` | não | income = renda recorrente. |
| `title` | string | não | mín. 1, máx. 200 |
| `amount` | string | não | Decimal em texto, até 2 casas. Ex.: "89.90". (padrão `^\d{1,16}([.,]\d{1,2})?$`) |
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
| `expected_version` | string | não | A `version` que você leu. Se o registro mudou desde então, a escrita volta CONFLICT (com a versão atual) em vez de sobrescrever a mudança de outra pessoa. (mín. 6, máx. 40, padrão `^[0-9a-f]+$`) |

**Saída (`structuredContent`)**: `recurring`, `previous`, `changed`, `replayed`

Exemplo:

```json
{"recurring_id": 7, "amount": "55.00"}
```

Exemplo:

```json
{"recurring_id": 7, "active": false}
```

### `recurring_delete` — Excluir recorrência

- **Classe:** Destrutiva · **Escopo:** `planning.write` · **Custo:** 3 unidade(s)
- **Annotations:** readOnlyHint=false, destructiveHint=true, idempotentHint=true, openWorldHint=false
- **UI (MCP Apps):** `ui://controle-financeiro/widget-v4.html` · chamável pelo componente

Exclui uma despesa ou renda recorrente: o app para de lançar novas ocorrências. O que já foi lançado continua (e continua contando), salvo `cancel_open_occurrences=true`, que cancela as ocorrências deste mês em diante ainda não pagas. Não tem desfazer: para só interromper, prefira pausar (recurring_update com active=false).

Use quando: o usuário pedir para excluir/apagar de vez uma recorrência (confirme qual).

Não use quando: quiser pausar, mudar o valor ou o fim (recurring_update).

**Entrada**

| Parâmetro | Tipo | Obrigatório | Descrição |
|---|---|---|---|
| `recurring_id` | integer | sim | ≥ 1 |
| `kind` | `expense` \| `income` | não |  |
| `cancel_open_occurrences` | boolean | não | Só despesa: true = cancela também as ocorrências JÁ lançadas deste mês em diante que ainda não foram pagas. false (padrão) = o que já foi lançado fica como está. |
| `expected_version` | string | não | A `version` que você leu. Se o registro mudou desde então, a escrita volta CONFLICT (com a versão atual) em vez de sobrescrever a mudança de outra pessoa. (mín. 6, máx. 40, padrão `^[0-9a-f]+$`) |

**Saída (`structuredContent`)**: `deleted`, `cancelled_occurrences`

Exemplo:

```json
{"recurring_id": 7}
```

Exemplo:

```json
{"recurring_id": 3, "kind": "income"}
```

### `budgets_set` — Definir meta do mês

- **Classe:** Escrita · **Escopo:** `planning.write` · **Custo:** 3 unidade(s)
- **Annotations:** readOnlyHint=false, destructiveHint=true, idempotentHint=true, openWorldHint=false
- **UI (MCP Apps):** `ui://controle-financeiro/widget-v4.html` · chamável pelo componente

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
| `amount` | string | sim | Quanto se pretende gastar no mês nessa categoria. Ex.: "89.90". (padrão `^\d{1,16}([.,]\d{1,2})?$`) |
| `month` | string | não | Mês da meta (YYYY-MM). Omitido = mês atual. (padrão `^\d{4}-(0[1-9]|1[0-2])$`) |
| `scope` | `personal` \| `space` | não | `personal` = sua meta (compara com a SUA parte); `space` = meta da casa (total do espaço). Obrigatório em espaço com mais de uma pessoa. |
| `note` | string | não | máx. 2000 |

**Saída (`structuredContent`)**: `id`, `space`, `category`, `month`, `scope`, `amount`, `created`, `app_url`

Exemplo:

```json
{"category": "Mercado", "amount": "800.00", "scope": "personal"}
```

### `categories_create` — Criar categoria ou tag

- **Classe:** Escrita · **Escopo:** `planning.write` · **Custo:** 3 unidade(s)
- **Annotations:** readOnlyHint=false, destructiveHint=false, idempotentHint=true, openWorldHint=false
- **UI (MCP Apps):** `ui://controle-financeiro/widget-v4.html` · chamável pelo componente

Cria uma categoria (ou, com `kind=tag`, uma tag) num espaço. Se já existir uma com o mesmo nome (ignorando acento e maiúsculas), devolve ALREADY_EXISTS com o id dela — use a existente.

Use quando: o usuário pedir uma categoria/tag que não existe (confira antes com categories_list).

Não use quando: ela já existir, mesmo escrita diferente; para renomear/excluir (categories_update).

**Entrada**

| Parâmetro | Tipo | Obrigatório | Descrição |
|---|---|---|---|
| `kind` | `category` \| `tag` | não | category (padrão) ou tag. |
| `space` | string | não | máx. 120 |
| `space_id` | integer | não |  |
| `name` | string | sim | mín. 1, máx. 120 |
| `color` | string | não | Cor em hex, ex.: #22C55E. (padrão `^#[0-9A-Fa-f]{6}$`) |

**Saída (`structuredContent`)**: `id`, `name`, `space`, `kind`

Exemplo:

```json
{"name": "Pets", "space": "Casa"}
```

Exemplo:

```json
{"kind": "tag", "name": "Trabalho"}
```

### `categories_update` — Renomear ou excluir categoria/tag

- **Classe:** Escrita · **Escopo:** `planning.write` · **Custo:** 3 unidade(s)
- **Annotations:** readOnlyHint=false, destructiveHint=true, idempotentHint=true, openWorldHint=false
- **UI (MCP Apps):** `ui://controle-financeiro/widget-v4.html` · chamável pelo componente

Renomeia, muda a cor ou exclui uma categoria ou tag de um espaço (`kind`). Nome novo que já exista volta erro.

Use quando: "renomeie Restaurantes para Alimentação fora", "apague a tag viagem-2024".

Não use quando: quiser criar (categories_create) ou trocar a categoria de lançamentos (transactions_update / transactions_bulk_preview).

**Entrada**

| Parâmetro | Tipo | Obrigatório | Descrição |
|---|---|---|---|
| `kind` | `category` \| `tag` | não |  |
| `space` | string | não | máx. 120 |
| `space_id` | integer | não |  |
| `name` | string | não | Nome ATUAL da categoria/tag. (máx. 120) |
| `id` | integer | não | ≥ 1 |
| `new_name` | string | não | Nome novo (renomear). (mín. 1, máx. 120) |
| `color` | string | não | padrão `^#[0-9A-Fa-f]{6}$` |
| `delete` | boolean | não | true = excluir. Categoria excluída some das listas (os lançamentos antigos a mantêm); tag excluída sai de todos os lançamentos. |

**Saída (`structuredContent`)**: `kind`, `id`, `name`, `previous_name`, `space`, `deleted`

Exemplo:

```json
{"name": "Restaurantes", "new_name": "Alimentação fora", "space": "Casa"}
```

Exemplo:

```json
{"kind": "tag", "name": "viagem-2024", "delete": true}
```

### `attachments_upload_link` — Link para anexar arquivo

- **Classe:** Escrita · **Escopo:** `transactions.write` · **Custo:** 3 unidade(s)
- **Annotations:** readOnlyHint=false, destructiveHint=false, idempotentHint=true, openWorldHint=false

Gera um link de envio de USO ÚNICO (10 minutos) para anexar a um lançamento um arquivo que está no computador do usuário (recibo, nota fiscal, comprovante: JPG, PNG, WebP ou PDF). O arquivo vai do terminal direto para o app, sem passar pela conversa. Devolve o comando `curl` pronto; rode-o e confira a resposta (`attachment_id`).

Use quando: você roda num terminal com acesso aos arquivos do usuário (Claude Code, Codex, Gemini CLI) e ele pede para anexar um arquivo a um lançamento.

Não use quando: não houver como executar comandos (ChatGPT e Claude na web): diga que o anexo se envia pela tela do lançamento no app. O link não lê nem apaga anexos.

**Entrada**

| Parâmetro | Tipo | Obrigatório | Descrição |
|---|---|---|---|
| `transaction_id` | integer | sim | ≥ 1 |
| `file_path` | string | não | Caminho do arquivo no computador do usuário, só para montar o comando pronto. (máx. 500) |

**Saída (`structuredContent`)**: `transaction_id`, `upload_url`, `authorization`, `form_field`, `expires_at`, `max_bytes`, `accepted_types`, `command`

### `attachments_get` — Ler anexo (recibo)

- **Classe:** Leitura · **Escopo:** `finance.read` · **Custo:** 3 unidade(s)
- **Annotations:** readOnlyHint=true, destructiveHint=false, idempotentHint=true, openWorldHint=false

Entrega o CONTEÚDO de um anexo de lançamento (foto do recibo, nota fiscal em PDF) para você ler — por exemplo, para extrair os itens da nota e registrá-los com transactions_update (`items`). Arquivos grandes demais voltam só com os dados e o link do app.

Use quando: o usuário pedir para ler, conferir ou detalhar o recibo de um lançamento (pegue o id em `files` de transactions_get).

Não use quando: só precisar saber se há anexo (transactions_get já diz).

**Entrada**

| Parâmetro | Tipo | Obrigatório | Descrição |
|---|---|---|---|
| `attachment_id` | integer | sim | O id do anexo (em `files` de transactions_get). (≥ 1) |

**Saída (`structuredContent`)**: `attachment`, `transaction_id`, `delivered`, `note`

### `attachments_delete` — Excluir anexo

- **Classe:** Destrutiva · **Escopo:** `transactions.write` · **Custo:** 3 unidade(s)
- **Annotations:** readOnlyHint=false, destructiveHint=true, idempotentHint=true, openWorldHint=false
- **UI (MCP Apps):** `ui://controle-financeiro/widget-v4.html` · chamável pelo componente

Apaga um anexo (recibo) de um lançamento, para sempre — não há como desfazer. Membro apaga os próprios anexos; administrador do espaço, qualquer um.

Use quando: o usuário pedir para remover um recibo anexado por engano (confirme qual, pelo nome do arquivo).

Não use quando: quiser excluir o lançamento (transactions_delete).

**Entrada**

| Parâmetro | Tipo | Obrigatório | Descrição |
|---|---|---|---|
| `attachment_id` | integer | sim | ≥ 1 |

**Saída (`structuredContent`)**: `deleted`, `transaction_id`

### `attachments_add` — Anexar arquivo da conversa

- **Classe:** Escrita · **Escopo:** `transactions.write` · **Custo:** 3 unidade(s)
- **Annotations:** readOnlyHint=false, destructiveHint=false, idempotentHint=true, openWorldHint=false
- **UI (MCP Apps):** `ui://controle-financeiro/widget-v4.html` · chamável pelo componente

Anexa a um lançamento um arquivo que o usuário colocou NESTA conversa (foto do recibo, nota em PDF) — no ChatGPT, que entrega o arquivo à tool. JPG, PNG, WebP ou PDF.

Use quando: o usuário mandar o recibo na conversa e pedir para anexá-lo a um lançamento.

Não use quando: o arquivo estiver no computador do usuário e você rodar num terminal (attachments_upload_link); ou o app de chat não entregar arquivos a tools — aí o anexo é pela tela do lançamento.

**Entrada**

| Parâmetro | Tipo | Obrigatório | Descrição |
|---|---|---|---|
| `transaction_id` | integer | sim | ≥ 1 |
| `file` | objeto | sim | O arquivo como o app de chat o entrega (`openai/fileParams`). |

**Saída (`structuredContent`)**: `attachment`, `transaction_id`
