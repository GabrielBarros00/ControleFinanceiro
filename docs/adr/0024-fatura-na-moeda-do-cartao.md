# ADR 0024 — A fatura é denominada na moeda do CARTÃO, e o lançamento tem duas pernas

**Status:** aceito (2026-08-10)
**Relacionado:** [0015](0015-conversao-na-entrada-e-taxa-cruzada.md) (conversão na entrada),
[0021](0021-recurso-pessoal-sem-workspace.md) (recurso pessoal),
[0011](0011-ciclo-de-fatura-e-pagamento.md) (ciclo da fatura),
[0023](0023-saldo-de-fatura-arquivo-e-data-efetiva.md) (saldo cumulativo)

## Contexto

Dois ADRs corretos, tomados em ondas diferentes, produziram juntos um defeito que
nenhum dos dois previa.

O **ADR 0015** decidiu que todo lançamento é convertido na ENTRADA para a
moeda-base do **workspace**: `currency`/`total_amount` ficam na base e o original
é congelado em `original_*`. O **ADR 0021** tirou o cartão do workspace e o
tornou pessoal — a moeda dele passou a ser a de **relatório do dono**, escolhida
uma vez e independente de qualquer workspace.

Nada conectava as duas moedas. E `compute_statement_total` somava
`Transaction.total_amount` filtrando `currency == card.currency`.

### O que isso produzia

Moeda de relatório USD, workspace em BRL, cartão em USD, uma despesa de R$ 100:

- o lançamento era gravado com `currency = "BRL"` (a base do workspace);
- o filtro exigia `"USD"`, não casava com **nenhuma** linha;
- `SUM` sobre conjunto vazio → `NULL` → total da fatura **US$ 0,00**;
- `available_limit = limit − 0` → o limite **nunca** era consumido;
- `close_statement` congelava `total_amount = 0.00`: o erro virava histórico;
- `overview_service` descartava a fatura do endividamento em silêncio, sem nem
  incrementar `excluded_foreign_count`;
- e a listagem da fatura — que não filtrava moeda **nem status** — exibia a
  compra, formatada com a moeda do cartão. R$ 100 apareciam como `−US$ 100,00`.

Três populações diferentes na mesma tela: o valor convertido para o workspace, o
total filtrado pela moeda do cartão, e uma lista que mostrava tudo. Sem erro, sem
aviso, sem contador.

O filtro por moeda não era um bug de digitação: ele implementava a política do
ADR 0006 ("o que não bate fica de fora em vez de entrar com uma conversão
inventada"). O que faltava era alguém ter decidido **em que moeda a fatura é
denominada** — e garantido que o valor nessa moeda existisse.

## Decisão

**1. O lançamento tem duas pernas.**

| Perna | Colunas | Moeda | Responde |
|---|---|---|---|
| **Contábil** | `currency`, `total_amount` | base do **workspace** | quanto a compra pesa no orçamento desta casa |
| **Fatura** | `statement_amount`, `statement_currency`, `statement_exchange_rate` | do **cartão** | quanto o banco vai cobrar |

A contábil não muda em nada. A de fatura é `NULL` para lançamento sem cartão.

**2. A conversão é na ENTRADA, como manda o ADR 0015.**
`compute_statement_conversion` converte da moeda em que a compra foi feita para a
do cartão, via `ExchangeRateStore.rate_between` — a fonte única — e com
`local_day` da data da compra. Sem cotação, `422`: recusar é melhor que gravar um
valor inventado.

**3. Listagem, total, limite, fechamento e pagamento operam sobre a MESMA
população.** `CreditCardService.statement_population` é o predicado, num lugar
só. As duas cópias que existiam divergiam em dois eixos — a listagem não filtrava
status (rascunho e cancelada apareciam) nem moeda —, e a tela mostrava linhas que
o rodapé não somava.

**4. O IOF da perna de fatura é ancorado no CARTÃO** (`currency !=
card.currency`), porque é o emissor quem converte e cobra o imposto. A perna
contábil continua com o critério dela (moeda-base do workspace). **Nos cenários
multimoeda os dois divergem** — uma compra em USD num cartão USD dentro de um
workspace BRL leva IOF na perna contábil e não na de fatura. Isso é uma
inconsistência **conhecida e deixada em aberto**: corrigi-la significa mudar o
critério contábil, o que reescreveria valores já gravados. Fica para uma onda que
trate disso de frente, com migração.

**5. O backfill é IDENTIDADE, não conversão retroativa.** A migração
`d8f1a37c025b` copia `total_amount`/`currency` para a perna de fatura. Acerta o
caso são — cartão e workspace na mesma moeda, a esmagadora maioria — e não
inventa um câmbio que banco nenhum cobrou, na linha do ADR 0015 ("o valor é
congelado na entrada, de propósito"). Converter histórico com a cotação de hoje
seria produzir um número novo e chamá-lo de passado.

**6. O que sobra fora do total é CONTADO, não silenciado.**
`excluded_from_total_count` viaja na fatura e a tela avisa — mesma política do
`excluded_foreign_count` da visão global. Quem quiser a conversão histórica roda
`scripts/backfill_statement_amounts.py`, que usa a taxa da data de cada compra e
falha alto quando ela não existe.

Esse script converte a linha **e recongela o total da fatura**. Só a transação não
basta: pelo ponto 3 acima, fatura fechada ou paga responde com o `total_amount`
congelado no fechamento, então converter a compra e parar aí apagaria o aviso de
linha incompatível e deixaria o total errado — pior que o estado anterior, porque
agora sem sinal nenhum de que está errado. Quando o total novo passa do já pago, a
fatura fica sub-paga: o script **anuncia e não age**. Mexer em `status` ou criar
pagamento seria decidir por quem opera se aquela diferença vai ser cobrada.

**7. A perna de fatura é invariante de modelo, não disciplina de rota.** O
listener `before_insert` de `Transaction` carimba a identidade quando há
`statement_id` e falta `statement_amount` — mesmo mecanismo (e mesmo motivo) do
`billing_month`. Quem sabe a moeda do cartão grava o valor convertido antes, e o
valor explícito vence.

**8. A moeda do cartão passa a ser escolhida na criação** (`CurrencyCombobox`) e
permanece **imutável** depois. Antes a UI não oferecia o campo: criar um cartão em
dólar exigia trocar a moeda de relatório, criar e destrocar. Trocá-la depois
reinterpretaria retroativamente todas as faturas dele.

## Consequências

- Um cartão global finalmente funciona em workspaces de moedas diferentes, que é
  o que o ADR 0021 prometeu e não entregava.
- `statement_exchange_rate` guarda taxa × IOF já combinados: é o fator que
  reconstrói a parcela na edição de compra parcelada, sem consultar câmbio de novo.
- O parcelamento fatia `statement_amount` com o mesmo `_split_amounts` do total,
  então as N parcelas somam exatamente a compra — recalcular por parcela deixaria
  a soma da fatura diferente por arredondamento.
- Fica de fora: cartão cuja moeda muda (não existe), e a divergência de critério
  do IOF descrita no ponto 4.
