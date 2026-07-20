# Recorrência materializa despesa COMPLETA; datas por mês de calendário

A recorrência gerava uma `Transaction` **nua** — sem pagador, divisão, categoria, método ou criador (REC-001). Sem pagador/divisão ela não entra em `DebtService` nem soma corretamente em relatórios: virava um número solto. Também não havia frequência diária nem escopo de edição, e financiamento/parcelamento avançavam datas com `timedelta(days=30)`, deslocando o vencimento e errando o rótulo de mês.

## Decisões

**Snapshot completo no template.** `RecurringExpense` guarda `currency`, `payment_method`, `category_id`, `payer_user_id` e `split_snapshot` (JSON de `{user_id, split_method, input_value}`). A materialização cria a transação E seus filhos pelo mesmo motor das despesas (`persist_transaction_children`), então a instância nasce como qualquer despesa: com pagador, divisão (que entra nas dívidas), categoria e método. Sem snapshot, o padrão é 100% ao pagador (criador) — nunca mais nua.

**Uma instância por ocorrência.** `Transaction.occurrence_date` + índice único `(recurring_expense_id, occurrence_date)`. A instância excluída mantém a linha (tombstone) e ocupa a vaga → a unique bloqueia recriação por natureza. Transações comuns têm `occurrence_date` NULL e não colidem (NULLs são distintos na unique).

**Frequência diária.** `RecurrenceFrequency.daily` gera uma ocorrência por dia; dedup por data exata (como semanal).

**Escopos de edição.** `PUT /recurring/{id}?scope=none|future|all`: editar o template reaplica valor/divisão/categoria às instâncias NÃO pagas — só a atual em diante (`future`, padrão), todas (`all`) ou nenhuma (`none`). Recria os filhos no valor novo, senão pagador/divisão divergiriam do total. Pagas/canceladas ficam congeladas.

**Datas por mês de calendário.** `app/domain/dates.py::add_months` (extraído do `_add_months` do parcelamento) preserva o dia limitado ao fim do mês. Financiamento passou a usá-lo no cronograma (era `days=30*i`).

**Pagar parcela de financiamento gera despesa.** O cronograma é só plano; ao pagar, cria-se uma `Transaction` (pagador+divisão do dono) — o gasto entra no caixa/relatórios apenas quando pago. Guardado por `is_paid`, não duplica.

**Importação em lote idempotente (ADR 0008).** `ImportBatch`/`ImportRow` com decisão por linha (`import`/`ignore`) e `fingerprint` (workspace, data, centavos, título): reimportar o mesmo arquivo marca as linhas como `duplicate` e não cria nada.

## Consequências

- Migração `a4c8e17b92d5` (idempotente): colunas de snapshot em `recurringexpense`, `transaction.occurrence_date` + índice único, tabelas `importbatch`/`importrow`.
- `sync_unpaid_instances` agora recria os filhos (antes só mexia em título/valor, deixando divisão inconsistente).
- FKs de `category_id`/`payer_user_id` ficam no modelo (create_all); a migração adiciona colunas simples e a aplicação valida categoria/membro.
