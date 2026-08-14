# ADR 0027 — Acertos existem nas duas camadas; a global é a visão da pessoa

**Status:** aceito (2026-08-13)
**Relacionado:** [0009](0009-acertos-sem-sobrepagamento.md) (teto e direção do acerto),
[0018](0018-privacidade-papel-e-acesso-financeiro.md) (papel × acesso financeiro),
[0020](0020-visao-global-e-quatro-numeros.md) (camada `/me/*`, saldos não se compensam),
[0006](0006-moeda-base-brl-sem-soma-mista.md) / [0015](0015-conversao-na-entrada-e-taxa-cruzada.md) (moeda)

## Contexto

"Acertos entre pessoas" era **do workspace de ponta a ponta**: nav em
`Dia a dia → Acertos` (`/w/:id/debts`), rota dentro do `WorkspaceGuard`, três
hooks com `workspaceId` na chave e na URL, e os routers
`/workspaces/{ws}/debts` e `/workspaces/{ws}/settlements`.

Quem participa de duas casas não tinha onde perguntar **"com quem eu me acerto,
somando tudo?"**. Para saber que devia 150 na Casa e tinha 80 a receber na Viagem
era preciso abrir cada workspace e somar de cabeça — a mesma lacuna que o ADR
0020 fechou para renda e resultado ao criar `/me/*`, e que ficou aberta aqui.

A única exposição cross-workspace de acerto era indireta e muda: os
`to_pay`/`to_receive` por casa em `/me/overview` e as fontes
`settlement_sent`/`settlement_received` do caixa em `/me/ledger`. Nenhuma das
duas diz **com quem**, e de nenhuma se registra um acerto.

## Decisão

**As duas telas convivem, e a diferença entre elas não é o alcance — é o
RECORTE.**

### 1. `/me/debts`, `/me/debts/monthly`, `/me/settlements` — a visão da pessoa

Gate `get_current_user`, como o resto de `/me/*`. Toda chamada ao `DebtService`
passa `viewer_user_id=user_id`, **inclusive para quem é admin ou owner**: a
camada pessoal é sempre `involved_only`.

É por isso que a tela da casa não vira redundante. Ela mostra a dívida **entre
terceiros** a quem tem `full_workspace` (ADR 0018) — o "Outros Acertos" —, e essa
pergunta ("como está esta casa") continua sendo dela. A global responde outra
("como estou eu"), e o mesmo par existe em Relatórios desde o ADR 0020.

A tela do workspace passa a **dizer isso em voz alta**: título `Acertos · {casa}`,
subtítulo "Somente esta casa", e um link para a global. Sem isso, quem tem duas
casas lê os números de uma como se fossem o total — que é exatamente o defeito
que o ADR 0020 corrigiu no Início.

### 2. Agrupa, nunca compensa

Dever 100 na Casa e ter 100 a receber na Viagem **não** é estar quitado: são
pessoas e acordos diferentes. A saída é agrupada por workspace, e a tela global
**não tem "saldo líquido"** — só `to_pay` e `to_receive` lado a lado. O líquido
continua existindo DENTRO de cada casa, onde significa alguma coisa.

### 3. A escrita continua sendo ato de UM workspace

`POST /workspaces/{ws}/settlements` segue sendo o único caminho: é lá que vivem a
direção e o teto do ADR 0009, o `trava_workspace` contra sobrepagamento
concorrente, o `require_role` e o `publish_event` — que **exige** workspace,
porque incrementa `Workspace.event_seq`.

A tela global manda o `workspace_id` da linha clicada. **É o que a distingue do
"Nova despesa" ausente na Visão global** (ADR 0020): lá o workspace de destino
seria ambíguo e a despesa cairia numa casa invisível; aqui ele vem da própria
linha, junto com o nome da casa impresso no diálogo.

Cada grupo carrega `role` e `can_write` (o mesmo gate de `require_role(member)`).
`WorkspaceRead` não traz papel, e sem ele a tela ofereceria um botão que só sabe
responder 403.

### 4. Moeda: omitir do total, nunca da tela

Cada grupo vem na **moeda-base da própria casa, sempre**. Só os totais do topo
convertem para `User.report_currency`, e a casa sem cotação sai da soma para
`excluded_workspaces`, **nomeada e com o valor na moeda dela**.

É mais estrito que o `/me/overview`, que derruba o workspace inteiro de
`by_workspace` e devolve só um contador. A regra do ADR 0006 é não somar o que
não converte; sumir com a informação é outra coisa, e "você deve R$ 0,00" para
quem deve USD 90 é o mesmo modo de falha que o `or ZERO` já produziu uma vez.

## Consequências

- `PersonalDebtService` **compõe**, não reimplementa: `DebtService` continua sendo
  a única definição de saldo e de pareamento. Uma segunda seria a divergência
  esperando acontecer.
- `OverviewService._workspaces_do_usuario` virou
  `query_policy.workspaces_do_usuario` — três serviços precisam do mesmo recorte,
  e a terceira cópia era a chance de um deles esquecer o `deleted_at`.
- `MonthlyLedgerBody` e `BalanceCards` saíram de `MonthlyDebtsSection`/`DebtsPage`
  para serem os mesmos nas duas telas. `/me/debts/monthly` devolve, por casa,
  campo a campo o payload de `/{ws}/debts/monthly` — mais `people`, com os nomes
  que a tela da casa buscaria em `/{ws}/members` e que a global não tem como
  buscar N vezes.
- `me-debts`, `me-debts-monthly` e `me-settlements` entram em `GLOBAIS`
  (`ws-events.ts`): são famílias de `/me/*` e a chave **não** leva workspace —
  `['me-debts', 7]` não casa com `['me-debts']`, o defeito da Onda 6.
- **Limite conhecido:** o WebSocket é por sala de workspace, então a tela global
  só recebe evento em tempo real das casas a que o cliente está inscrito. Mesmo
  limite de `/me/overview`; a invalidação local pós-mutação cobre quem age.
- **Custo:** `/me/debts` chama `get_workspace_debts` uma vez por casa, e ele varre
  o histórico inteiro daquela casa — a mesma parte cara que fez `get_series`
  ganhar o `com_acertos=False`. Aceitável porque é uma tela e não um laço de 12
  meses, mas não deve ser chamado dentro de um.
- **Desfazer acerto continua na casa.** Não é limitação de rota: `DELETE` exige
  `require_role` e autoria, e o histórico global lista acertos de casas onde o
  papel varia. A linha leva para a casa dele.
- Fica de fora, conscientemente: o item de nav se chama **"Seus acertos"**, não
  "Acertos". Dois itens com o mesmo nome em seções diferentes foi o problema que
  "Compromissos" resolveu, e o par certo é o de "Seus relatórios" × "Relatórios".
