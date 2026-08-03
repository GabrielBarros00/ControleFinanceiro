# Saldo de fatura, arquivamento que preserva histórico, e a data efetiva de verdade

Status: aceito, 2026-07-31. Relacionados: 0011 (ciclo da fatura), 0022 (caixa
efetivo), 0009 (acertos sem sobrepagamento), 0015 (conversão na entrada), 0006.

Uma auditoria externa encontrou um defeito P0 e cinco P1 na camada financeira.
Eles parecem independentes, mas três dos seis têm a mesma origem: **um número
agregado nascia de uma consulta própria, com o seu filtro e a sua data**, em vez
de sair das linhas que ele resume. Quando o total e o detalhe são consultas
diferentes, eles divergem — é só questão de quando.

## Contexto

- Pagar R$ 1 numa fatura de R$ 1.000 devolvia `status = paid`, liberava o limite
  inteiro do cartão e ainda **impedia** completar o pagamento (a fatura já não
  estava `closed`). Nada no backend somava `StatementPayment.amount`, embora o
  schema sempre tenha admitido N pagamentos por fatura.
- Excluir um cartão ou um financiamento **apagava retroativamente** pagamentos
  que já tinham acontecido: as consultas de caixa filtravam `deleted_at`, então
  arquivar o cadastro reescrevia meses fechados.
- A parcela de financiamento gerava a despesa espelhada na data de **vencimento**
  e na moeda do financiamento, crua. Pagar adiantado zerava o caixa do mês em que
  o dinheiro saiu; e uma parcela em USD num workspace BRL virava uma despesa que
  **nenhuma agregação somava**, porque todas filtram `currency == base`.
- Cancelar a despesa vinculada fazia a saída sumir dos **dois** lados: a
  transação caía pelo status, e a parcela caía porque "existe uma transação".
- O caixa convertia moeda estrangeira pela cotação do **dia 1º do mês**, embora o
  ADR 0022 declare, na sua própria tabela, "seis fontes, cada uma com a sua data
  efetiva".
- A janela do mês era um `datetime.combine` ingênuo sobre o calendário local,
  comparado contra colunas que guardam instantes UTC.

## Decisões

### 1. A fatura tem SALDO, e ele é cumulativo

`CardStatement` ganha dois números derivados: `paid_amount` (soma dos pagamentos
vivos) e `remaining_amount` (`effective_total − paid_amount`, nunca negativo).

- `pay_statement` sem valor paga **o saldo**, não o total congelado.
- Valor acima do saldo é **recusado**, citando o saldo e a moeda — a mesma regra
  que o ADR 0009 aplica aos acertos entre pessoas: aceitar mais do que se deve
  inventa crédito.
- A fatura só vira `paid` quando o saldo chega a zero; até lá continua `closed` e
  aceita o próximo pagamento.
- **O limite comprometido passa a ser o saldo**, não o total. Pagar metade libera
  metade.
- Reabrir estorna os pagamentos nas **duas** transições (`paid→closed` e
  `closed→open`): uma fatura aberta volta a somar em tempo real, e não haveria
  saldo a que o pagamento se referisse.

### 2. Arquivar não reescreve o passado

As consultas de caixa **deixam de filtrar** `CreditCard.deleted_at` e
`Financing.deleted_at`. O fato é o `StatementPayment` / a
`AmortizationInstallment`; o cadastro é rótulo. É o modelo que `PaymentAccount`
já usava — soft-delete com o histórico apontando para a linha morta.

Os filtros **permanecem** em compromissos (`/me/commitments`): obrigação futura
de cadastro arquivado não é compromisso.

Excluir um financiamento **ativo com parcelas em aberto** passa a exigir
confirmação explícita (`?cancel_open_installments=true`), no espírito do guard
que o cartão já tinha. As parcelas não pagas continuam gravadas como não pagas —
o cancelamento é reconstituível, em vez de sumir junto com o cadastro.

### 3. A despesa da parcela segue a data e a moeda de um lançamento comum

`paid_at` passa a ser informável no pagamento da parcela, e é dele que saem
`transaction_date` e `billing_month` da despesa vinculada. A conversão usa o
**mesmo** `compute_base_conversion` dos lançamentos (extraído de
`api/routes/transactions.py` para `services/base_conversion.py`), sem IOF —
parcela não é compra internacional no cartão.

O vínculo passa a ser **imutável** nos campos que definem a identidade financeira
(valor, data, mês, moeda, workspace): a dedup do caixa escolhe entre contar a
despesa OU a parcela, e as duas precisam continuar falando do mesmo pagamento.
Título, categoria e divisão entre pessoas seguem editáveis — isso é sobre como a
casa rateia, não sobre o pagamento.

### 4. A deduplicação olha o STATUS, não só a existência

O `EXISTS` da parcela exige `Transaction.status IN REALIZED_STATUSES`. Sem isso,
uma despesa cancelada suprimia a parcela sem entrar no lugar dela.

### 5. O caixa é uma lista de linhas; os totais saem dela

`CashFlowService` passa a expor `list_movements`, que devolve cada movimento com
a sua **data efetiva**, a sua moeda e o valor convertido por aquela data.
`get_month` agrega essas linhas — e os dois `breakdown` saem das mesmas linhas do
total, então não há como divergirem.

Isso corrige a conversão (cada movimento pela cotação do seu dia, com a taxa
memoizada por `(moeda, dia)`) e entrega, de graça, o **extrato global**
(`GET /me/ledger`): a mesma lista, filtrada. O detalhe fecha com o total por
construção, não por disciplina.

### 6. O aplicativo tem UM fuso, e ele é explícito

`settings.APP_TIMEZONE` (padrão `America/Sao_Paulo`) e três helpers em
`domain/dates.py`: `app_tz()`, `today_local()` e `month_bounds_utc()`.

O backend tinha duas referências de "hoje" convivendo — `datetime.now(UTC)` na
classificação de fatura vencida e compromissos, `date.today()` na recorrência, na
previsão e na data de cotação. Em fuso negativo elas discordam todo dia entre 21h
e a meia-noite. O fuso existia apenas como `TZ` nos serviços do Compose:
invisível para o `Settings` e **ausente** em qualquer uvicorn iniciado à mão —
dev local, CI, Playwright.

A janela do mês passa a ser o mês de calendário **local** convertido para
instantes UTC. Uma renda recebida às 22h de 31 de julho em São Paulo está gravada
como `2026-08-01T01:00Z` e pertence a **julho**.

### 7. `billing_month` é derivado no fuso do app — onde a proveniência é conhecida

`transaction_date` é ambíguo por natureza: chega ora como **instante** de verdade
(o cliente manda `new Date().toISOString()`), ora como **dia de calendário à
meia-noite** (linha de CSV, cronograma de parcelas, fixture). A conversão de fuso
só é correta no primeiro caso — aplicada ao segundo, `datetime(2026, 5, 1)` vira
competência de abril.

Por isso a regra é por CAMADA, não global:

- **As rotas convertem** (`month_key_local`): elas sabem que o corpo do POST/PUT
  traz um instante ISO. Vale para criar, editar a data, parcelar e o lote.
- **O import de CSV não converte**: a linha é um dia de calendário.
- **O listener de mapper não converte**: é o catch-all, e a proveniência ali é
  desconhecida por definição.

O formulário sempre mandou `billing_month` explícito e mascarava o defeito. Quem
chamava a API sem ele — script, integração, o e2e — gravava competência do mês
seguinte durante três horas todo dia, e o lançamento não aparecia em tela
nenhuma. Era o que reprovava `e2e-prod/realtime_invite`: o evento de WebSocket
chegava e a invalidação rodava; o lançamento é que estava no mês errado.

## Consequências

- Contrato da API: `/me/credit-cards/.../statements` ganha `paid_amount`,
  `remaining_amount` e `payments`, e deixa de devolver `Dict[str, Any]` — os
  schemas vivem em `app/schemas/credit_card.py` e o frontend deriva deles.
- `POST .../installments/{n}/pay` aceita `paid_at`.
- `DELETE /me/financing/{id}` pode responder 409.
- Endpoint novo: `GET /me/ledger`.
- `tzdata` entra em `requirements.txt`: o Windows não tem base de fusos do
  sistema, e sem ela o `zoneinfo` degradava para UTC justamente onde a diferença
  importa.
- **Sem migração de schema.** `paid_amount`/`remaining_amount` são derivados, e
  `StatementPayment` já existia como lista.

## O que fica de fora

Não há reconversão retroativa de movimentos já convertidos: corrigir uma cotação
publicada errada continua fora de escopo (ADR 0015). E `net_cash` segue sendo o
movimento do mês, não saldo bancário — o app não modela contas com saldo.
