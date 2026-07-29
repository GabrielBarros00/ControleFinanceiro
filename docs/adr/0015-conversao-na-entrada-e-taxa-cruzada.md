# Lançamento em moeda estrangeira é convertido na ENTRADA, pela taxa cruzada da moeda-base

**Supersede o [ADR 0006](0006-moeda-base-brl-sem-soma-mista.md)** (e a parte de moeda do [ADR 0014](0014-consultas-moeda-e-experiencia.md)).

## Contexto

O ADR 0006 decidiu **segregar**: transação em moeda diferente da base ficava fora das agregações até existir taxa histórica congelada. Na prática isso deixava o gasto invisível — quem viaja e compra em euro via o mês parecer mais barato do que foi, sem nenhum sinal.

Com o store histórico de câmbio (`ExchangeRate` + backfill diário) a taxa por data passou a existir, então a razão da segregação caiu.

Uma segunda força: `Workspace.base_currency` é configurável na UI desde a Onda 5 (Configurações → Moeda-base, com dry-run e reconversão do histórico). Mas todo o caminho de ENTRADA assumia que a base era BRL — `ExchangeRateStore.get_or_fetch` devolve X→**BRL** por contrato e os quatro conversores tratavam esse número como X→**base**. Num workspace em USD, uma despesa de EUR 50 era gravada como 315 USD; e uma despesa em BRL (o default dos formulários) virava o mesmo número em dólar, com taxa 1,0.

## Decisão

**1. Converter na entrada, não segregar.** Um lançamento estrangeiro é convertido para a moeda-base do workspace no momento em que é criado. `total_amount`/`currency` ficam na base; o original é congelado em `original_amount`, `original_currency`, `exchange_rate`, `iof_rate`, `rate_source`, apenas para exibição. Como tudo vira base internamente, nenhuma agregação precisou mudar.

**2. A taxa é sempre `from → base`, calculada como cruzada.** O store guarda apenas X→BRL, então `ExchangeRateStore.rate_between(db, from, to, data)` = `(from→BRL) / (to→BRL)` é a **fonte única** — usada pela criação/edição de lançamento, pela renda, pela materialização de recorrência, pela projeção e pela troca de moeda-base. `get_or_fetch` continua existindo, mas só como "X→BRL"; quem converte para a base não o chama direto.

**3. Selo de origem honesto.** `rate_source` é `ptax` só quando a PTAX é oficial para aquele par — ou seja, contra o real. Taxa cruzada entre duas moedas estrangeiras é `market`.

**4. IOF de 3,5%** (Decreto 12.499/2025, `settings.IOF_INTERNATIONAL_CARD_RATE`) entra apenas em compra internacional no cartão (crédito/débito), congelado por lançamento.

**5. Recorrência re-converte por ocorrência**, com a taxa do dia daquela ocorrência — não congela o câmbio do template.

**6. Nenhum default de moeda é literal.** Onde a moeda não vem informada, ela é resolvida por `resolve_currency(session, ws_id, currency)` → moeda-base do workspace (com normalização de caixa). O mesmo vale no frontend, via `useBaseCurrency()`.

**7. A moeda-base ainda filtra as agregações.** Um lançamento legado gravado em outra moeda continua fora dos totais, e a contagem (`excluded_foreign_count`) é exibida ao usuário para ele saber que sumiu de propósito.

## Consequências

- `ExchangeRateStore.rate_between` é o único ponto onde a matemática de câmbio existe.
- A conversão exige cotação **das duas** moedas na data; o que faltar vira `422` na entrada e `MissingRates` na troca de moeda-base. O serviço `cron` do Compose mantém o store quente (`scripts/backfill_rates.py`).
- No caminho de LEITURA (materialização preguiçosa) a busca on-line é proibida (`allow_fetch=False`): um GET não pode ficar preso numa fonte externa. Sem cotação, a ocorrência espera o backfill em vez de nascer com valor inventado.
- Fica de fora: converter novamente quando a cotação de uma data é corrigida a posteriori. O valor é congelado na entrada, de propósito — é o que o extrato bancário mostra.
