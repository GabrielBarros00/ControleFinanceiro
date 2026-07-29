> **SUPERSEDED** pelo [ADR 0015](0015-conversao-na-entrada-e-taxa-cruzada.md): desde 2026-07-23 o
> lançamento em moeda estrangeira é **convertido na entrada** (o store histórico de câmbio passou
> a existir), em vez de ficar fora das agregações. A moeda-base por workspace continua valendo.

# Moeda-base BRL por workspace; agregações nunca somam moedas diferentes

Agregações (dívidas, relatórios, orçamento) somavam valores de moedas distintas diretamente e relatórios convertiam para `float`. Decidimos: cada workspace tem moeda-base (BRL por padrão); agregações operam em `Decimal` e **rejeitam/segregam** transações de moeda diferente da base enquanto não houver taxa histórica congelada por transação (planejada para a Onda 5 — o `CurrencyService` PTAX atual só fornece taxa do dia, o que não serve para valores históricos).
