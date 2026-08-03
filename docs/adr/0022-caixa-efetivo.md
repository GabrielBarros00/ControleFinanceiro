# ADR 0022 — Caixa é quando o dinheiro se move, não quando a despesa é assumida

**Status:** aceito (2026-07-31)
**Relacionado:** [0020](0020-visao-global-e-quatro-numeros.md) (visão global),
[0021](0021-recurso-pessoal-sem-workspace.md) (recurso pessoal),
[0006](0006-moeda-base-brl-sem-soma-mista.md) (moeda-base),
[0002](0002-statement-id-derivado-no-servidor.md) (fatura derivada)

## Contexto

O ADR 0020 introduziu "Saída de caixa" como o número que faltava no app — e o
implementou como `Σ TransactionPayer` do mês de faturamento. O nome estava errado.

Esse número responde *"quanto eu assumi das despesas deste mês"*. Não responde
*"quanto dinheiro saiu da minha conta"*, e a diferença aparece no caso mais comum
que existe:

> Compra de R$ 300 no cartão em 5 de julho. Fatura paga em 10 de agosto.

| Mês | "Saída de caixa" (antes) | Dinheiro que realmente saiu |
|-----|--------------------------|------------------------------|
| julho  | R$ 300 | R$ 0 — o dinheiro ainda está na conta |
| agosto | R$ 0   | R$ 300 |

O erro não era só de data. Três movimentos de dinheiro **não existiam em lugar
nenhum** do sistema:

- **pagamento de fatura** (`StatementPayment`) — o momento em que o cartão vira
  dinheiro de verdade, e a única fonte que conhece pagamento parcial;
- **acerto enviado a outro membro** (`Settlement`) — dinheiro que muda de mão;
- **parcela de financiamento paga** sem lançamento em workspace — o caso do
  compromisso puramente pessoal.

Uma aba chamada "Fluxo de Caixa" desenhava tudo menos fluxo de caixa. E o defeito
era estrutural, não de rótulo: nenhum ledger existia, então nenhum nome
consertaria o número.

## Decisão

**Separar competência de caixa, e nomear os dois pelo que são.**

### 1. O número antigo vira `paid_in_transactions`

`cash_out` passa a se chamar `paid_in_transactions` — "o que assumi nos
lançamentos". Ele **continua existindo e continua recortado por workspace**,
porque é ele que fecha o acerto entre membros: `to_pay`/`to_receive` são sobre
*quem assumiu o quê*, não sobre *quando o dinheiro saiu*. Alice adiantar a conta
do restaurante cria um crédito no instante da despesa, independentemente de ela ter
pago no cartão.

### 2. `cash_in` / `cash_out` passam a ser caixa de verdade

Seis fontes, cada uma com a sua data efetiva e a sua moeda
(`app/services/cashflow_service.py`):

| Direção | Fonte | Data | Moeda |
|---------|-------|------|-------|
| saída   | `TransactionPayer` de lançamento **sem** `credit_card_id` | `transaction_date` | do lançamento |
| saída   | `StatementPayment` de fatura de cartão meu | `paid_at` | do cartão |
| saída   | `Settlement` que eu enviei | `settled_at` | base do workspace |
| saída   | parcela de financiamento meu, paga | `paid_at` | do financiamento |
| entrada | `Income` | `received_at` | da renda |
| entrada | `Settlement` que eu recebi | `settled_at` | base do workspace |

`credit_card_id IS NULL` é o discriminador da primeira linha: a compra no cartão
não é caixa, é dívida com o banco, e vira caixa quando a fatura é paga.

### 3. Caixa é GLOBAL, sem recorte por workspace

Pagamento de fatura e parcela de financiamento não moram em workspace nenhum
(ADR 0021). Forçá-los num — o do cartão? o do último lançamento? — reintroduziria
exatamente a premissa que aquele ADR removeu. `by_workspace` continua carregando
`consumption` e `paid_in_transactions`, que são fatos do workspace.

### 4. Nada é contado duas vezes

Pagar uma parcela informando um `workspace_id` cria uma `Transaction` ligada por
`Transaction.financing_installment_id`. Quando essa despesa existe, é ela que
conta (fonte 1) e a parcela é ignorada; quando não existe, a parcela conta
sozinha. Sem a regra, quem lança a parcela no workspace pagaria duas vezes no
gráfico.

### 5. `result` não muda

`result = renda − consumo` continua sendo o resultado do mês. É competência, e
estava certo. Caixa é outra pergunta e agora tem os seus próprios campos —
inclusive `cash_out_breakdown`, sem o qual "saiu R$ 4.200" não é auditável pelo
usuário, que não teria como saber se a fatura entrou na conta ou não.

## Consequências

**O que melhora.** O mês passa a ter as duas leituras que uma pessoa precisa:
"quanto do gasto foi meu" e "quanto dinheiro entrou e saiu". Pagamento parcial de
fatura, acerto e financiamento pessoal deixam de ser invisíveis. E a aba "Fluxo de
Caixa" passa a desenhar fluxo de caixa.

**O que quebra.** `cash_out` muda de significado na API. É uma quebra de contrato
deliberada: manter o nome antigo com o valor antigo perpetuaria o erro, e manter o
nome com o valor novo sem avisar seria pior. O campo antigo continua disponível sob
o nome honesto. As rotas `/me/*` ganharam `response_model` tipado
(`app/schemas/overview.py`) — antes devolviam `Dict[str, Any]`, o `api.gen.ts` não
recebia tipo nenhum e o frontend mantinha interfaces escritas à mão que divergiam
em silêncio.

**O que fica de fora.** Não há saldo de conta bancária: o app não sabe quanto há em
cada conta, só o que se moveu. `net_cash` é o movimento do mês, não um saldo. Saldo
por conta exige saldo inicial e conciliação — outra decisão, se algum dia.

Transferência entre contas da própria pessoa também não existe como conceito; se um
dia existir, é a sétima fonte e precisa se anular (sai de uma, entra na outra).
