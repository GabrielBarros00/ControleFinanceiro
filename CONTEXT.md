# CONTEXT — o vocabulário do Controle Financeiro

O glossário do domínio: o que cada termo da tela significa, como ele se chama no
código, e onde a decisão está registrada (`ADR NNNN` = `docs/adr/NNNN-*.md`).

Aqui só há **significados**. As regras completas e o porquê moram nos ADRs e no
[ARCHITECTURE.md](docs/ARCHITECTURE.md); como trabalhar no repositório está no
[AGENTS.md](AGENTS.md). Criou um termo novo na tela ou no código? Acrescente aqui.

## Armadilhas de nome

Nomes que já causaram defeito por dizerem uma coisa e significarem outra.

| No código | Parece | É |
|---|---|---|
| `Income.received_at` | quando a renda caiu | a **competência**: quando ela *era para* entrar. Quando caiu é `Income.settled_at` (ADR 0034) |
| `status = paid` | "já paguei" | a **trava** da despesa, que protege o histórico de acertos. "Já paguei" é `settled_at` preenchido (ADR 0029) |
| `Workspace.settlement_tracking` | algo dos acertos (`Settlement`) | o controle de **Contas a pagar**: fora do cartão, a despesa só vira saída de caixa depois de marcada como paga (ADR 0029) |
| `Transaction.billing_month` | o mês da fatura | a **competência** (mês local da `transaction_date`). O mês da fatura é `CardStatement.month` |
| `total_amount` de compra estrangeira | o valor da compra | o valor **já convertido** para a moeda-base. O da compra é `original_amount` (ADR 0015) |
| `transaction_date` | um dia | um **instante**. Um dia do calendário vira instante ao meio-dia local; meia-noite volta um dia em São Paulo (ADR 0025) |
| `MonthlyEstimate.user_id` | de quem é a meta | quem **criou**. O escopo da meta é `owner_user_id`, e vazio = meta da casa (ADR 0017) |
| `StatementStatus.overdue` | um estado gravado | nunca é gravado: "vencida" é derivada na leitura (`CreditCardService.is_overdue`) |

## Onde as coisas vivem

- **Espaço** (na tela, a seção "Compartilhado" com o nome do espaço) = `Workspace`.
  É onde as pessoas colaboram: lançamentos, divisão, acertos, categorias,
  recorrências, metas da casa. URL `/w/:workspaceId/...` (ADR 0020).
- **Pessoal** ("Só você vê") = a camada `/me/*`. Cartão, conta, renda e financiamento
  são da PESSOA: não têm `workspace_id`, têm dono (`owner_user_id`; na renda, `user_id`).
  O cartão é meu e eu o uso em qualquer espaço, mas ele nunca pertence ao espaço
  (ADR 0021).
- **Papel** (`WorkspaceMembership.role`: `owner` > `admin` > `member` > `viewer`): o
  que a pessoa pode FAZER no espaço.
- **Acesso financeiro** (`financial_access`: `involved_only` | `full_workspace`): o
  que a pessoa pode VER. É independente do papel (ADR 0018).
- **Envolvimento**: criou, pagou, tem parte na divisão ou participa de um item
  (`involvement_filter`). Quem não está envolvido e não tem acesso completo não vê a
  linha, e o que é invisível responde 404, não 403.
- **Dono do espaço**: a membership com papel `owner`, não quem criou o espaço. A
  posse pode ser transferida (ADR 0028).
- **Papel de plataforma** (`User.platform_role`: `user` | `admin` | `superadmin`):
  opera o site (convites, configurações, métricas). Não dá acesso a dado financeiro de
  ninguém (ADR 0026).

## O lançamento

- **Lançamento** = `Transaction`. O `total_amount` está na moeda-base do espaço.
- **Pagadores** (`TransactionPayer`): quem pagou, quanto e de onde (`payment_method`,
  `account_id`). Cada pagador tem a própria origem (ADR 0004).
- **Divisão** (`TransactionSplit`): de quem é quanto. `split_method` é `equal`,
  `percentage` ou `fixed`, sempre fechando o total ao centavo (ADR 0001).
  - **Divisão por item** (`split_mode = item`): cada `TransactionItem` tem as próprias
    partes (`TransactionItemShare`), e a divisão da despesa é derivada delas.
  - **Ajustes** (`TransactionAdjustment`): desconto, frete, gorjeta, cashback… entram no
    total.
- **Valor cheio × minha parte**: o `total_amount` é do lançamento inteiro; a minha
  parte é a soma das minhas divisões (`my_share`). Na tela, o número em destaque é
  sempre o da pessoa, e o valor cheio aparece nomeado ("de R$ X").
- **Status** (`TransactionStatus`): `draft`, `pending`, `confirmed`, `paid`,
  `cancelled` (ADR 0003).
  - *Realizado* é `confirmed` + `paid` (`REALIZED_STATUSES`).
  - `pending` entra só na previsão e em Contas a pagar.
  - `draft` e `cancelled` não entram em nada.
- **Liquidar / "já paguei"** = preencher `settled_at`: o dinheiro saiu. Não é o
  `status = paid` (ver as armadilhas). Liquidar promove `pending` → `confirmed`
  (ADR 0029, ADR 0034).
- **Parcelada**: cada parcela é um lançamento. As parcelas compartilham
  `installment_group_id`, e cada uma tem `installment_no` de `installments_of`. Editar
  **a parcela** muda só ela; editar **a compra inteira** reconstrói o grupo e congela
  as parcelas já pagas.
- **Recorrência** (`RecurringExpense`: `frequency` + `interval` + `start_date`/`end_date`)
  gera **ocorrências**: lançamentos materializados com `occurrence_date`. A ocorrência
  excluída deixa marca e não volta (ADR 0012, ADR 0030).
- **Categoria** e **tag**: do espaço. A categoria fica no item do lançamento.

## Tempo: competência, caixa, saldo e previsão

Quatro perguntas diferentes, cada uma com a sua fonte. Nenhum valor é lido de duas
(ADR 0034).

| Eixo | Pergunta | Fonte | Na tela |
|---|---|---|---|
| **Competência** | de qual mês é? | `billing_month` + `status` (renda: `received_at`) | relatórios, resultado, acertos |
| **Caixa** | quando o dinheiro se moveu? | `settled_at`, `paid_at` (`CashFlowService`) | **Extrato** (`/me/ledger`) |
| **Saldo** | quanto existe em cada conta? | ledger da conta (`AccountBalanceService`) | **Contas** |
| **Previsão** | o que ainda vai entrar ou sair? | obrigações não liquidadas (`PayablesService`, `ProjectionService`) | **Contas a pagar**, projeção |

Consequências que confundem:

- compra no cartão **não** é saída de caixa; vira caixa quando a fatura é paga;
- transferência entre contas minhas não é entrada nem saída;
- ajuste de saldo não é renda;
- renda prevista não é entrada.

**Datas**: fuso único `APP_TIMEZONE` (America/Sao_Paulo) (ADR 0025).

- "Hoje" é `today_local()`, nunca `date.today()`.
- Dia de calendário → instante: `civil_instant` (meio-dia local).
- Instante → dia ou mês: `local_day` e `month_key_local`.
- No frontend: `parseApiDate` lê instante; `parseApiDay` lê dia de calendário, como o
  vencimento da fatura.

## A visão do mês (os quatro números)

Os números da camada pessoal (`OverviewService`), somando todos os espaços da pessoa
(ADR 0020, ADR 0022):

- **Consumo**: Σ das minhas divisões, quanto do gasto foi meu.
- **Saída de caixa**: o dinheiro que saiu de verdade, pelas fontes do caixa. Não
  confundir com `paid_in_transactions`, "o que assumi nos lançamentos" (Σ dos meus
  pagadores), que é o que fecha o acerto entre membros.
- **A pagar / a receber**: por espaço. **Nunca se compensa entre espaços**: dever 100
  na casa e ter 100 a receber da viagem não é estar quitado.
- **Resultado do mês**: renda − **consumo** (não − caixa). Adiantar dinheiro por outra
  pessoa é crédito a receber, não gasto.

## Pessoas: dívidas, acertos e compromissos

- **Dívida entre membros**: nasce quando alguém paga a parte de outra pessoa (pagadores
  × divisão). Dividir uma despesa, por si só, não gera dívida.
- **Acerto** (`Settlement`): o dinheiro que quita dívida entre membros (ADR 0009).
  - Só vai na direção da dívida, com teto no saldo (sem sobrepagamento).
  - Membro comum só registra acerto em que ele é quem paga; acerto de terceiros exige
    `admin` ou `owner`.
  - É registrado no espaço (`POST /{ws}/settlements`); `/me/settlements` só lê, somando
    os espaços (ADR 0027).
- **Acerto do mês × acerto do acumulado**: o do mês tem `billing_month` e fecha aquele
  mês; o sem mês abate o acumulado. Saldo acumulado = Σ dos meses + o que não tem mês
  (ADR 0031). Saldo de um mês se lê de `net_debts`, que já desconta os acertos, e não
  de `members[].balance`.
- **Acertos × Compromissos**: **acertos** são entre pessoas e se resolvem com uma
  transferência. **Compromissos** (`/me/commitments`) são com terceiros (fatura do
  cartão, financiamento) e se resolvem pagando o banco.
- **Contas a pagar** (`/me/payables`, `/w/:id/payables`): o que ainda vai sair do caixa
  FORA do cartão (boleto, Pix, dinheiro), com `status` em `PAYABLE_STATUSES` e
  `settled_at` vazio. Fatura e parcela de financiamento ficam em Compromissos.

## Cartão e fatura

- **Cartão** (`CreditCard`, pessoal): `closing_day`, `due_day`, `limit`, `currency`.
- **Fatura** (`CardStatement`): `month`, `closing_date`, `due_date`, `status`
  (`open` → `closed` → `paid`, com reabertura).
  - É **derivada no servidor** a partir de cartão + data; nunca vem do cliente
    (ADR 0002).
  - Pagar fatura gera `StatementPayment`, e ela aceita pagamentos parciais. O **saldo**
    (`remaining_amount`) é o total menos o que já foi pago. Pagar sem informar o valor
    paga o saldo, e a fatura só vira `paid` quando ele zera (ADR 0023).
- **Deslocamento de fatura** (`statement_shift`): o emissor pôs a compra noutra fatura
  (+1 = a próxima). É relativo, e move a fatura sem mover a competência (ADR 0032).
- **Perna de fatura** (`statement_amount`, `statement_currency`): o mesmo lançamento na
  moeda do CARTÃO, que é onde a fatura cobra. `total_amount` é a perna contábil, na
  moeda do espaço (ADR 0024).

## Moeda

- **Moeda-base** (`Workspace.base_currency`): em que o espaço soma.
- **Moeda de relatório** (`User.report_currency`): em que o que é pessoal soma. Nunca
  assuma BRL no código: leia a moeda do espaço, da pessoa, do cartão ou da conta.
- **Conversão na entrada**: lançamento em outra moeda vira moeda-base na hora (ADR 0015).
  - A cotação é a do dia: PTAX quando existe, mercado senão, e taxa cruzada por
    `ExchangeRateStore.rate_between`.
  - IOF só em compra com cartão, de crédito ou de débito (`iof_rate`).
  - O original fica em `original_amount`, `original_currency`, `exchange_rate` e
    `rate_source`.
  - Na edição, o valor é lido na moeda original. Mudar valor, data, moeda ou cartão
    reconverte, pela edição completa. O caminho parcial da API (`PUT` sem `payers`) não
    converte nada, e é por isso que o SPA e o MCP não o usam para isso.
- Nada soma moedas diferentes: o que não converte fica de fora, com contagem (ADR 0006).

## Contas, renda, financiamento, metas, importação

- **Conta** (`PaymentAccount`: `checking`, `savings`, `cash`, `digital_wallet`,
  `other`), pessoal. O saldo é derivado:
  - a **abertura** (`AccountEntry` com `kind = opening_balance`) é o ponto de partida,
    e só conta o que vem depois da data dela;
  - o **ajuste** (`adjustment`) concilia com o extrato do banco;
  - a **transferência** (`AccountTransfer`) é uma linha só, com as duas pernas.
  - Movimento que declara conta tem de estar na moeda dela (ADR 0034).
- **Renda** (`Income`), pessoal. Três estados:
  - **prevista**: `settled_at` vazio, aparece em "A receber";
  - **recebida**: `settled_at` preenchido, com `account_id` se souber;
  - **cancelada**: `cancelled_at`, continua visível.
  - Renda recorrente = `RecurringIncome`.
- **Financiamento** (`Financing`, `SAC` | `PRICE`), pessoal. Parcelas em
  `AmortizationInstallment`; o saldo devedor é o principal que falta
  (`remaining_balance`), sem os juros futuros. A
  **quitação em lote** marca parcelas pagas antes de o app existir (`paid_outside_app`),
  e isso não é saída de caixa (ADR 0023).
- **Meta / orçamento** (`MonthlyEstimate`): valor por categoria e mês, da casa ou
  pessoal. A meta pessoal é comparada com a parte da pessoa, não com o total da casa
  (ADR 0017).
- **Importação** (`ImportBatch`, `ImportRow`): CSV com `fingerprint` por linha para
  apontar duplicata. Cada linha é importada, ignorada, marcada como duplicata ou pulada
  por ser inválida, sempre com trilha (ADR 0008).

## Agentes de IA (MCP)

Ver [docs/mcp/](docs/mcp/README.md) e o ADR 0035.

- **Tool**: uma ação por intenção ("registrar despesa", "mostrar fatura"), nunca um
  endpoint cru.
- **Tool de dados × tool de exibição**: as de dados (`transactions_get`,
  `statements_get`, `reports_summary`…) só devolvem dados. As de exibição
  (`transactions_show`, `statements_show`, `reports_show`) fazem a mesma consulta e
  desenham o componente na conversa. Componente em tool de dados fazia o ChatGPT criar
  um iframe a cada consulta do agente (ADR 0035).
- **Escopo** (`finance.read`, `transactions.write`, …): o que a conexão pode fazer. Vale
  junto com o papel e a visibilidade, nunca no lugar deles.
- **Conexão / concessão** (`OAuthGrant`): a autorização que a pessoa deu a um
  aplicativo. "Desconectar" revoga.
- **Chave de idempotência** (`idempotency_key`): repetir a mesma chave não cria de novo.
- **Prévia + token de confirmação**: exclusão e recategorização em massa só executam o
  conjunto que foi mostrado.
- **"via IA"** na auditoria: `AuditLog.origin = "mcp:<cliente>"`.
- **Link de envio** (`cfm_up_…`): token de uso único que `attachments_upload_link` emite
  para o agente de terminal mandar um arquivo com `curl` a `POST /api/v1/mcp/uploads`.
  O arquivo não passa pela conversa; a rota reconfere tudo e grava pelo mesmo comando
  da tela (`services/commands/attachments.py`).
