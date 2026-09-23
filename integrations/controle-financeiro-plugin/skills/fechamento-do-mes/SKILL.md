---
name: fechamento-do-mes
description: Fecha o mês financeiro com o usuário — resumo de renda, consumo e resultado, contas ainda a pagar, dívidas entre pessoas em aberto e metas estouradas, com a lista do que falta resolver.
---

Use quando o usuário pedir o fechamento, balanço ou resumo do mês.

1. `profile_get` para saber o mês atual e o fuso (o "mês passado" é relativo a
   `today`).
2. `reports_summary` do mês: renda, **seu** consumo (a parte do usuário nas
   despesas divididas), resultado, o que saiu do caixa e as maiores categorias.
3. `payables_list`: o que ainda falta pagar (contas, faturas, parcelas de
   financiamento), com vencimentos.
4. `debts_summary` do mês: quem deve a quem em cada espaço. Espaços diferentes
   **não se compensam** — apresente por espaço.
5. `budgets_list`: metas estouradas ou perto do limite.
6. `income_list`: rendas previstas que ainda não caíram.
7. Termine com uma lista curta de pendências e ofereça as ações:
   marcar conta como paga (`transactions_update` com `settled: true`), registrar
   acerto (`settlements_create`), confirmar renda recebida (`income_update` com
   `status: received`). Cada ação só depois do "sim" do usuário, uma
   `idempotency_key` nova por intenção.
8. Se o usuário quiser VER o resumo desenhado na conversa, chame `reports_show`
   uma vez, no fim. Para calcular e comparar, use só as tools de dados: cada
   `*_show` desenha um componente novo.

Não invente números nem arredonde: repita os valores das tools, na moeda indicada.
