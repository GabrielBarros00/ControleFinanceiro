# ADR 0021 — Recurso financeiro pertence à pessoa e não mora em workspace nenhum

**Status:** aceito (2026-07-30)
**Supersede:** [0019](0019-propriedade-pessoal-com-compartilhamento.md) (compartilhamento por workspace)
**Relacionado:** [0018](0018-privacidade-papel-e-acesso-financeiro.md) (papel × acesso),
[0020](0020-visao-global-e-quatro-numeros.md) (visão global),
[0015](0015-conversao-na-entrada-e-taxa-cruzada.md) (moeda na entrada)

## Contexto

O ADR 0019 acertou o diagnóstico — renda, cartão, conta e financiamento são da
pessoa — e errou o remédio: manteve o recurso ancorado num workspace e
acrescentou tabelas de vínculo para estendê-lo a outros. Uma auditoria externa
mostrou que o meio-termo não se sustentava.

### O vazamento

`CardWorkspaceAccess` tinha dois níveis com um contrato explícito: `use` deixava
o workspace lançar compras e ver o próprio subtotal; `full` abria a fatura
inteira. O predicado que implementava a distinção, `card_full_access_here()`,
existia em `access_policy.py` — **e não era chamado por rota nenhuma**. Na
prática, todo cartão compartilhado entregava a quem tivesse `full_workspace` no
workspace de destino:

- limite e valor comprometido do dono;
- a fatura inteira, incluindo as compras feitas em **outro** workspace.

`GET .../statements/{id}` piorava: filtrava as transações **só** por
`statement_id`, sem workspace e sem envolvimento. E `close`, `pay` e `reopen`
pediam apenas `require_role(member)` — qualquer membro que enxergasse o cartão
controlava o ciclo da fatura de outra pessoa.

### E, ao mesmo tempo, não servia

Usar o cartão compartilhado no workspace de destino respondia `400`: a criação de
lançamento exigia `card.workspace_id == workspace_id`. O mesmo valia para conta
de pagamento (`_validate_payer_accounts`). O recurso aparecia na listagem de lá e
era recusado no formulário.

### O número que mentia

A meia-medida contaminou os relatórios. `my_income` virou global (correto: a
renda segue a pessoa) enquanto `my_expenses` continuou recortado no workspace, e
o Painel exibia a diferença como "Resultado do mês". Com salário de 9.000 e 1.150
de despesa na Casa, ele anunciava **7.850 de sobra** — ignorando os 500 gastos
noutro workspace. Num terceiro workspace o mesmo salário seria combinado com
outro subconjunto de despesas e daria uma terceira "sobra". Nenhuma delas era o
resultado da pessoa, e todas eram maiores que o real.

A renda "da casa" (`scope="workspace"`) tinha defeito irmão: sem modelo de
beneficiários, a visão global creditava o valor **inteiro** a quem cadastrou. O
aluguel recebido pelo casal aparecia todo para um só.

## Decisão

**Recurso financeiro pessoal não tem `workspace_id`.**

| Camada | Entidades | Dono | Quem vê |
|---|---|---|---|
| **Pessoal** (`/me/…`) | `Income`, `RecurringIncome`, `CreditCard`, `PaymentAccount`, `Financing` | coluna de dono **NOT NULL** | só o dono |
| **Workspace** (`/w/:id/…`) | `Transaction` e filhos, `Category`, `RecurringExpense`, `MonthlyEstimate`, `Settlement`, `Attachment`, `Tag`, `AuditLog` | `workspace_id` NOT NULL | papel + `financial_access` |

1. **As cinco tabelas de vínculo somem** (`CardWorkspaceAccess`,
   `PaymentAccountWorkspaceShare`, `FinancingWorkspaceShare`,
   `IncomeWorkspaceShare`, `RecurringIncomeWorkspaceShare`), junto com o enum
   `CardAccessLevel` e o `scope` da renda.

2. **`personal_scope(column, user_id)` é o único gate desses recursos, e não
   consulta `financial_access`.** Esta é a assimetria central:

   > `financial_access=full_workspace` governa dado **do workspace** — total da
   > casa, lançamento alheio, composição por categoria. Recurso **pessoal** ele
   > não alcança, em papel nenhum.

   O predicado anterior (`owner_scope`) devolvia `true()` para quem tinha acesso
   completo. Trocar o modelo sem trocar o predicado teria reaberto o vazamento
   por baixo, com o schema novo.

3. **O gate de uso é a propriedade, não o workspace.** Lançar com um cartão exige
   `card.owner_user_id == quem lança`; a conta de um pagador tem de pertencer
   **àquele pagador** (`_validate_payer_accounts` nunca olhava `payer.user_id` —
   bastava conhecer o id para declarar que a despesa saiu da conta bancária de
   outra pessoa do mesmo workspace).

4. **A moeda de recurso pessoal é `User.report_currency`**, nunca a moeda-base do
   workspace aberto. E trocar a moeda-base de um workspace deixa de reescrever
   renda/conta/cartão dos membros — era um workspace alterando o cadastro pessoal
   de cada um, e num usuário de dois workspaces o segundo desfazia o primeiro.

5. **Renda e resultado saem dos números do workspace.** `/analytics/summary`
   perde `my_income`, `my_net`, `total_income` e `net_savings`; o histórico perde
   a série de receita; a previsão perde renda e fatura. Ganha o par que faltava:
   `paid_by_me` e `my_balance` — "paguei 1.300, consumi 1.150, tenho 150 a
   receber". Renda e resultado existem num lugar só, `/me/overview`, onde o
   denominador é o consumo somado de **todos** os workspaces.

6. **Compromissos separados por prazo.** `/me/commitments` devolve `overdue`,
   `due_this_month`, `next_installments`, `outstanding_total` e
   `monthly_commitment`, no lugar de um `total` que somava a próxima fatura com o
   principal inteiro dos financiamentos.

7. **Rotas de coleção em `/me` respondem com e sem barra final.** O
   redirecionamento 307 do Starlette descarta o cookie de sessão: `/me/income/`
   devolvia 401 enquanto `/me/income` devolvia 200.

## Consequências

**O que melhora.** A privacidade deixa de depender de cada endpoint lembrar de
filtrar: sem `workspace_id`, não existe consulta escopada por workspace capaz de
alcançar o recurso. O cartão passa a ser utilizável em qualquer workspace do dono
— que é o que o compartilhamento tentava e não conseguia entregar. E o app perde
seu número mais enganoso.

**O que se perde.** Não há mais como oferecer um cartão, uma conta ou um
financiamento a outra pessoa, nem receita "da casa". O caso real por trás disso —
o casal que divide tudo mas mantém contas separadas — continua legítimo e fica
**deliberadamente sem resposta nesta onda**, porque a resposta anterior estava
errada de forma: vinculava o recurso a um ESPAÇO quando o que o caso pede é
co-propriedade entre PESSOAS. O desenho está em
[`docs/estudo-recursos-compartilhados.md`](../estudo-recursos-compartilhados.md).

**Pagar parcela de financiamento** deixou de criar despesa automaticamente. A
despesa gerada nascia com pagador e divisão 100% do dono — nunca foi mecanismo de
rateio, só um registro de caixa que por acaso morava na casa dos outros. O corpo
do POST aceita `workspace_id` opcional para quem quer a parcela visível (e
divisível) no orçamento de uma casa.

**Recurso pessoal não emite evento de tempo real.** O canal é por sala de
workspace, e não existe sala para a qual transmitir — inventar uma seria
transmitir dado pessoal a uma sala de outras pessoas. Quem alterou já recebe o
valor novo na resposta, e é a única pessoa a quem isso interessa.

**Migração.** `a4e8c1b90f52` faz o backfill do dono a partir do workspace (membro
`owner`, ou o mais antigo), remove as colunas e derruba as tabelas de vínculo. A
unicidade do nome da conta passa de `(workspace, nome)` para `(dono, nome)`: duas
pessoas podem ter uma conta "Nubank", a mesma pessoa não.
