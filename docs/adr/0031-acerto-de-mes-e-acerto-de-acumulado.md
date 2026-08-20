# Acerto tem duas naturezas: fecha um mês ou abate o acumulado — e a tela diz qual

`Settlement.billing_month` existe desde que o ledger mensal nasceu, e é opcional.
Preenchido, o acerto quita **aquele mês**; nulo, ele abate apenas o **saldo
acumulado**. As duas coisas sempre estiveram no modelo, no `POST` e na resposta
de `GET /{ws}/settlements` — e em lugar nenhum da interface.

O efeito prático era um sistema que se contradizia em silêncio. Quem registrava
pelo bloco "Saldo geral a acertar" gravava `billing_month = NULL`: o total caía,
e **nenhum mês fechava**. A pessoa voltava ao retrato de julho e continuava
devendo os mesmos R$ 120 que acabara de pagar. Sem nada na tela nomeando a
diferença, a leitura possível era "o app errou".

A segunda metade do problema é que os dois números nunca foram calculados do
mesmo jeito, e isso também não estava escrito:

- `get_workspace_debts` soma **todos** os meses e desconta **todos** os acertos;
- `get_monthly_ledger` soma um `billing_month` e desconta **só** os acertos
  marcados com ele.

Como o listener de `models/transaction.py` preenche `billing_month` a partir de
`transaction_date`, `billing_month` particiona todo lançamento e todo acerto do
workspace. Disso decorre uma identidade exata que ninguém havia enunciado — e
que, não enunciada, permitia ler o acumulado como uma cobrança do mês corrente.

## Decisões

**1. A identidade é contrato, não coincidência.**

```
saldo acumulado == Σ (saldo de cada mês) + (o que não tem mês)
```

`GET /{ws}/debts/by-month` (e o par `/me/debts/by-month`) devolve a soma aberta:
uma linha por mês com saldo diferente de zero, uma linha `unassigned` para o que
não pertence a mês nenhum, e uma linha `older` para os meses além do teto da
lista. Os três termos existem para a conta **fechar na tela**. Uma quebra que não
fecha é pior do que não existir: a pessoa deixa de confiar nos dois números, não
só no que falta.

Consequência para quem for mexer: os filtros de `get_balance_by_month` têm de ser
byte a byte os de `get_workspace_debts` — mesmo conjunto de status, mesma
moeda-base, mesmo `deleted_at`. Divergir quebra a identidade **em silêncio**,
porque os dois números continuam plausíveis. `older` existe pela mesma razão:
truncar a lista sem somar o resto devolveria um total que não bate com as linhas
exibidas.

**2. As duas naturezas do acerto são visíveis.** Todo acerto no histórico carrega
o mês que fecha, ou a marca **"sem mês"**. Não é ausência de dado — é um tipo, e
um traço o faria parecer campo vazio.

**3. Recorte e saldo se separam.** Em `by-month`, o recorte do ADR 0018 vale para
`net_debts` de cada mês, **não** para `balance`. O saldo é o da pessoa por
inteiro; recortá-lo devolveria um total diferente do que `/debts` mostra na mesma
tela.

**4. Nada é agregado entre casas.** Na camada `/me/*` a origem vem por espaço, sem
total no topo. Somar a origem de casas diferentes produziria exatamente a
compensação que o ADR 0020 proíbe — com o agravante de parecer uma conta fechada.

## O que fica de fora

A **regra** de acerto não muda: direção e teto (ADR 0009), a trava contra
sobrepagamento concorrente e o `publish_event` seguem intactos, e a escrita
continua sendo `POST /workspaces/{ws}/settlements` mesmo quando disparada da tela
global (ADR 0027). Este ADR não cria comportamento — enuncia o que o modelo já
fazia e a interface escondia.

Também fica de fora **obrigar** um mês no acerto. O acerto de acumulado é
legítimo ("acertamos tudo, esquece os meses"); o defeito nunca foi ele existir, e
sim ele ser indistinguível do outro.
