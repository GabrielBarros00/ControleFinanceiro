# ADR 0034 — Saldo, caixa e previsão: quatro perguntas, quatro respostas

**Status:** aceito (2026-09-01)
**Relacionado:** [0022](0022-caixa-efetivo.md) (caixa efetivo),
[0029](0029-liquidacao-competencia-e-caixa.md) (liquidação),
[0004](0004-origem-de-pagamento-por-pagador.md) (origem por pagador),
[0021](0021-recurso-pessoal-sem-workspace.md) (recurso pessoal),
[0006](0006-moeda-base-brl-sem-soma-mista.md) (moeda-base)

## Contexto

O app sabia responder duas perguntas e achava que eram quatro.

O ADR 0022 separou **competência** ("de quem é o gasto") de **caixa** ("quando o
dinheiro se moveu") e listou seis fontes de movimento. O ADR 0029 acrescentou
`settled_at` e a fila de Contas a pagar. O que continuou sem resposta — e o
próprio ADR 0022 registrou a ausência — foi **saldo** ("quanto dinheiro existe") e
**previsão** ("o que ainda vai entrar e sair"):

> Não há saldo de conta bancária: o app não sabe quanto há em cada conta, só o que
> se moveu. Saldo por conta exige saldo inicial e conciliação — outra decisão, se
> algum dia.

Três defeitos concretos vinham daí:

1. **A conta de 18/09 cadastrada em 28/08 não aparecia em Contas a pagar.** A
   materialização cobria só o mês corrente, e `PayablesService` filtrava
   `REALIZED_STATUSES` — que não inclui `pending`. A ocorrência existia e não era
   obrigação para o sistema.
2. **Renda não distinguia prevista de recebida.** `Income` tinha uma data só e
   nenhum estado: o salário do dia 30 ou não existia até o dia 30, ou já contava
   como recebido no dia 1º. Não havia terceira opção, e a que o app fazia era a
   segunda.
3. **`PaymentAccount` era um rótulo.** Duas FKs opcionais apontavam para ela e
   nenhum serviço de leitura as consultava.

## Decisão

### 1. Quatro eixos, quatro fontes de verdade

| Pergunta | Eixo | Fonte | Serviço |
|---|---|---|---|
| De qual mês é este gasto/renda? | **Competência** | `billing_month` + `status` | `OverviewService` |
| Quando o dinheiro se moveu? | **Caixa** | `settled_at` / `paid_at` | `CashFlowService` |
| Quanto dinheiro existe? | **Saldo** | ledger da conta | `AccountBalanceService` |
| O que ainda vai entrar/sair? | **Previsão** | obrigação não liquidada | `PayablesService` + `ProjectionService` |

Nenhum valor é lido de dois eixos. Ajuste não é renda; transferência não é caixa;
compra no cartão não é saída; renda prevista não é entrada.

### 2. `PAYABLE_STATUSES` — obrigação tem conjunto próprio

Contas a pagar passa a usar `(pending, confirmed, paid)`; o caixa continua em
`REALIZED_STATUSES`. A ocorrência materializada para o dia 18 é obrigação no dia
1º **e** não é gasto realizado — as duas coisas ao mesmo tempo. A alternativa
óbvia (acrescentar `pending` ao conjunto do realizado) contaminaria relatório,
dívida entre membros, fatura e o resultado do mês com despesa que não aconteceu.

**Liquidar promove `pending → confirmed`**, e este é o ponto mais perigoso da
onda: sem a promoção, a despesa paga sai da lista e não entra no caixa — o
dinheiro some dos dois lados, em silêncio, e o único sinal é um saldo que não
fecha. `tests/api/test_contas_a_pagar_futuras.py` é o portão.

### 3. Renda ganha caixa, espelhando o ADR 0029

`Income.received_at` vira a **competência** ("quando era para entrar") e
`Income.settled_at` é o **caixa** ("quando entrou"); `NULL` é renda prevista.
`cancelled_at` é a prevista que não veio — visível como cancelada e segurando a
vaga da unique de ocorrência, ao contrário de `deleted_at`.

Coluna própria, e não um enum `expected|received`, pela razão registrada no ADR
0029: competência e caixa são ortogonais, e um estado único que significasse as
duas coisas voltaria a amarrá-las. O `status` que a API expõe é **derivado**
(`income_status`), nunca armazenado.

`resolve_income_settled_at` é o ponto único de decisão, com um gate de AST
(`tests/test_liquidacao_renda_ponto_unico.py`) — e o gate verifica também que
nenhuma construção use `**kwargs` sem nomear a decisão, porque a varredura casa
por substring e um `Income(**data)` a cegaria para sempre.

**`RecurringIncome.auto_confirm` nasce LIGADO**, ao contrário do `auto_settle` da
despesa. Renda recorrente é tipicamente salário e o comportamento de sempre foi
"chegou a data, entrou"; nascer desligado obrigaria todo mundo a confirmar à mão,
todo mês, o que sempre contou sozinho. Desligar é para renda incerta. Ligado ou
não, **a ocorrência nunca nasce recebida antes da data**.

### 4. `overview.income` passa a ser competência

Era o `income` do `CashFlowService`, ou seja, caixa. Enquanto `Income` tinha uma
data só isso não se notava; com renda prevista, `result = income − consumption`
passaria a subtrair um consumo de competência de uma renda de caixa, e o salário
do dia 30 zerava o resultado do mês até cair na conta. Quanto de fato entrou
continua respondido — e agora **só** — por `cash_in_breakdown.income`.

### 5. Saldo: o ledger existente ganha a dimensão conta

Não há ledger novo. `CashFlowService` já é o ledger; replicar seus movimentos numa
tabela de saldo daria duas fontes para o mesmo fato. O que se acrescenta:

- **`CashMovement.account_id`**, projetado pelas seis fontes. `Income`,
  `AmortizationInstallment` e `Settlement` ganharam a coluna;
  `TransactionPayer` e `StatementPayment` já a tinham.
- **`AccountEntry`** (`opening_balance` | `adjustment`) e **`AccountTransfer`** —
  as três coisas que não têm origem em tabela nenhuma.

```
saldo(conta) =  abertura + Σ ajustes
              + Σ transferências recebidas − Σ enviadas
              + Σ entradas de caixa − Σ saídas
              ... contando só o que ocorreu A PARTIR da data da abertura.
```

**A transferência é UMA linha com as duas pernas.** Duas linhas ligadas por um id
comum dependeriam de a aplicação lembrar de escrever as duas; assim, perna órfã
deixa de ser representável — a garantia é do esquema.

**Nada disso é fonte do `CashFlowService`.** Transferência entre contas minhas
infla `cash_in` e `cash_out` em igual medida e o `net_cash` acerta por acidente;
ajuste não é renda. `tests/test_caixa_sem_saldo.py` é a guarda mecânica: as fontes
de caixa continuam sendo seis, e `cashflow_service` não importa o ledger de saldo.

### 6. Saldo derivado, nunca cacheado

Dez consultas por tela — as seis fontes de caixa, as duas do ledger próprio, a
lista de contas e as aberturas —, **independentes do número de contas**: o
agrupamento é em memória, não um laço que repetiria tudo por conta. Quatro razões
deste projeto para não cachear:

1. **Colide com a auditoria automática**: os listeners de mapper gravariam uma
   linha de `AuditLog` por movimento por conta.
2. **Teria sete mantenedores**, e um deles já estava quebrado — `recurring_service`
   reconstruía o pagador sem `account_id` e apagava a conta em silêncio.
3. **Concorrência**: `saldo += x` é lê-depois-escreve e exigiria trava por conta na
   escrita mais frequente do app.
4. **Contradiz o pedido**: é literalmente o número sobrescrito sem rastro.

Se um dia doer, a saída é memoizar a RESPOSTA, não o número.

### 7. A invariante que sustenta tudo: moeda da conta = moeda do movimento

O saldo soma `amount` literalmente. Num workspace de base USD todo
`TransactionPayer.amount` está em USD, e antes desta onda dava para declarar que
ele saiu de uma conta em reais. `PaymentAccount.currency` vira a unidade de conta
do saldo, com gate nos pontos de escrita — e **`AccountTransfer` é o único lugar
do sistema onde duas moedas se encontram**, com valor de origem, de destino e taxa
declarados.

Três consequências: trocar a moeda-base de um workspace com pagamentos atribuídos
vira **409** (a troca reescreve `TransactionPayer.amount`, que alimenta o saldo
PESSOAL de cada membro); reativar conta com histórico preserva a moeda; e o total
agregado é conversão **de cortesia**, pela cotação de hoje, rotulada como tal — a
verdade de cada conta é o número na moeda dela.

### 8. Horizonte de materialização: regra de calendário

Mês corrente + mês seguinte inteiros. Em 28/08 vai até 30/09; em 1º/09, até
31/10. "Hoje + 30 dias" daria 27/09 no primeiro caso e deixaria de fora a última
semana do mês, onde ficam salário e a maioria dos vencimentos.

**O cron (`scripts/materializar_ocorrencias.py`, de hora em hora) é o mecanismo
principal; a materialização preguiçosa continua como rede de segurança, com o
MESMO horizonte.** Um app que se comporta diferente conforme o cron esteja rodando
é impossível de depurar. O script roda antes de `avisar_vencimentos.py`: avisar
sobre uma conta exige que ela exista.

### 9. Acerto recebido tem porta própria

`Settlement` ganhou `from_account_id` e `to_account_id`, e **cada lado só pode ser
preenchido pelo seu dono**. Quem registra o acerto é o pagador; a conta do credor
é invisível para ele, e declará-la violaria a regra que o projeto já escreveu em
`_validate_payer_accounts` — *"você não pode declarar de qual conta de outra
pessoa saiu o dinheiro"*. Daí o `PUT /me/settlements/{id}/account`.

## Consequências

**O que melhora.** As 17 perguntas do pedido passam a ter resposta, e a última —
*"por que o saldo atual é exatamente esse valor?"* — é respondida pelo extrato da
conta, linha a linha, com saldo corrente. A conta do dia 1º do mês seguinte é
conhecida antes da virada. O salário de 30/09 é visível o mês inteiro sem ser
declarado recebido.

**O que fica de fora, deliberadamente.**

- **Nenhum saldo histórico é reconstruído.** Os dados existentes não permitem
  inferir quanto havia em conta nenhuma. Toda conta nasce sem abertura e a tela
  pede o número. Um zero ali seria um valor errado com a cara de um certo.
- **Movimento sem conta continua legítimo** — e continua fora do saldo. O que não
  pode é ser mudo: há dois contadores na tela de Contas, um para "sem conta" e
  outro para "anterior ao saldo inicial", que é o caso em que a pessoa lança em
  janeiro o extrato de dezembro e o número não se mexe.
- **Pares `Income` + `Transaction` que hoje simulam transferência não são
  migrados.** Meses fechados não se reescrevem; a tela de transferência é o
  caminho daqui pra frente.

**O que o ADR precisa dizer em voz alta.** **O saldo não é reproduzível como o de
um banco.** Ele é função do estado ATUAL de seis tabelas mutáveis: desmarcar o
pagamento de uma conta tira a saída do saldo, corrigir uma data a move de mês, e
um `admin` pode liquidar lançamento de terceiro. O extrato explica o saldo de
hoje; ele não é o registro imutável de um fechamento. Dizer isso é melhor do que
fingir o contrário.
