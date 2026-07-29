# Changelog

Todas as mudanças relevantes deste projeto são documentadas aqui.
O formato segue [Keep a Changelog](https://keepachangelog.com/pt-BR/1.1.0/) e o versionamento
segue [SemVer](https://semver.org/lang/pt-BR/).

> **Sobre a versão:** `APP_VERSION` (`backend/app/core/config.py`, hoje `4.0.0`) nomeia a
> LINHA do produto — é o "V4" do nome — e aparece no `/health` para identificar o binário
> em produção. Ainda não há release tagueada: tudo abaixo é o caminho até a 4.0.0 e vive em
> `[Não lançado]`. Ao cortar a primeira tag, mova este bloco para `## [4.0.0] - AAAA-MM-DD`.

## [Não lançado]

### Corrigido — auditoria 2026-07-29 (4ª rodada)

- **O onboarding gravava renda e cartão fora da moeda-base.** `POST /auth/onboarding`
  construía `Income` e `CreditCard` sem informar `currency`, então os dois herdavam o
  default `"BRL"` do model. Num workspace em outra moeda o salário nascia **invisível**:
  toda agregação filtra `currency == base_currency` — e o formulário ainda exibia o
  símbolo da moeda-base, prometendo US$ e gravando BRL. Era o 10º e último caminho de
  entrada fora da regra (os outros nove já tinham regressão; este não estava lá).
- **O onboarding podia lançar o salário no workspace de outra pessoa.** O cliente mandava
  o workspace ativo, escolhido como o primeiro item de uma listagem **sem `ORDER BY`**;
  quem se cadastra por convite nasce com dois workspaces (o pessoal e o compartilhado).
  Agora o destino é sempre um workspace do qual a pessoa é `owner`, resolvido no servidor,
  e `GET /workspaces/` tem ordem explícita.
- **Relatórios e Lançamentos discordavam do mês na virada.** As agregações de despesa
  recortavam por uma janela sobre `transaction_date` (um INSTANTE gravado em UTC)
  enquanto o extrato e as dívidas usavam `billing_month` (o mês de calendário local).
  Uma despesa lançada às 22h do dia 31 em Brasília aparecia em Lançamentos e Dívidas de
  julho e nos Relatórios de **agosto** — a mesma despesa, na mesma sessão, em dois meses.
  Agora há **uma única definição de mês** (`billing_month`), garantida por listener de
  mapper para toda linha nova e por uma migração de backfill para as antigas.
- **`GET /analytics/exchange-rate` podia congelar a API.** É a única rota que ainda vai à
  rede de forma síncrona; o look-back de 5 dias do PTAX faz o pior caso chegar a ~10
  requisições de saída, e o backend roda com 1 worker. Sem teto, algumas chamadas
  concorrentes com códigos variados (cache miss garantido) esgotavam o threadpool. Agora
  tem balde próprio de 30/min por workspace, aplicado **antes** do I/O.
- **A CSP liberava WebSocket para qualquer host.** `connect-src 'self' ws: wss:` — os
  esquemas curinga abriam o canal clássico de exfiltração pós-XSS. `'self'` sozinho já
  cobre `ws://`/`wss://` do mesmo host.
- **Leitura escrevia no banco, inclusive para `viewer`.** A materialização preguiçosa roda
  no topo de 4 rotas `GET`: um papel somente-leitura provocava `INSERT` + `COMMIT` só de
  abrir o extrato, e todo workspace pagava as consultas de dedup e um commit por
  listagem mesmo sem nada a materializar. Dois curto-circuitos antes de qualquer escrita.
- **A troca de moeda-base não convertia as contas de pagamento** — a conta seguia rotulada
  na moeda antiga numa tela em que todo o resto já tinha migrado.
- **O onboarding era um modal na mão** (`<div className="fixed inset-0">`): sem
  `role="dialog"`, sem foco preso, sem devolver o foco. É a **primeira** tela de um
  usuário novo. Migrado para o `Dialog` do app, bloqueante de propósito — e o "X" agora é
  removido do DOM em vez de escondido por CSS (escondido, continuava focável pelo Tab).
- **`POST /auth/register` fazia quatro commits.** Se o seed de categorias falhasse, o
  usuário ficava criado e sem workspace, sem rollback possível. Commit único (ADR 0010).
- **Convite por e-mail expirado ficava "pendente" para sempre** — a lista do admin
  anunciava convites mortos como ativos, e cada reenvio deixava mais uma linha.
- **Item de despesa aceitava valor negativo** na borda (`ge=0` faltava no schema): quem
  reduz o total é o ajuste, que tem sinal explícito e validador próprio.
- Convite **por link** para quem ainda não tem conta perdia o token no desvio
  `/invite/<token>` → `/login` → `/register`: a pessoa se cadastrava e não virava membro
  de nada.

### Adicionado — auditoria 2026-07-29 (4ª rodada)

- **Moeda-base na criação do workspace.** Antes todo workspace nascia em BRL e a única
  forma de mudar era o `PUT`, que reconverte todo o histórico — uma operação pesada e
  sujeita a `MissingRates` para um workspace ainda vazio.
- `healthcheck` no container do frontend (é o único exposto ao host) e
  `ATTACHMENT_STORAGE_DIR` + volume de anexos no serviço `cron`.

### Corrigido — auditoria 2026-07-29 (3ª rodada)

- **Excluir um cartão de crédito deixava a fatura em aberto órfã.** O soft delete só escondia
  o cartão: as faturas não pagas continuavam existindo, mas fechar/pagar/reabrir exigem um
  cartão vivo — não havia como quitá-las. Pior, a dívida sobrevivia só de um lado: a
  **Previsão** somava aquelas faturas (o filtro não olhava `deleted_at`) e o **Endividamento**
  não, então as duas telas mostravam dívidas diferentes para o mesmo mês, sem nada por onde
  reconciliar. Agora o `DELETE` devolve **409** enquanto houver fatura em aberto com valor, e
  a previsão passou a filtrar cartão excluído.
- **Editar só o valor de uma despesa (PUT parcial) não atualizava o item que carrega a
  categoria.** A distribuição por categoria dos Relatórios soma `TransactionItem.amount`:
  a fatia ficava congelada no valor antigo e a diferença virava uma fatia "Sem categoria" que
  não existe. O gráfico fechava com o total e mentia na composição — que é o que se lê ali.
  Os itens agora acompanham o novo total, rateados em centavos exatos.
- **O total "saídas" da tela de Lançamentos contava despesa cancelada e rascunho** (e somava
  lançamento legado em outra moeda junto com a moeda-base), enquanto "Sua despesa" no Início
  usa só os status realizados: os dois números nunca fechavam. A soma passou a seguir a
  política única (ADR 0003/0006); a lista continua mostrando tudo, com a pílula de status.
- **Código de moeda não era validado.** Ele desce até a URL da fonte de câmbio de mercado
  (`.../v1/currencies/{codigo}.json`), então um parâmetro de query escolhia o caminho de uma
  requisição que o servidor faz para fora; e um código inventado era gravado no lançamento e
  sumia de **todas** as agregações (que filtram `currency == base_currency`) sem aviso. Agora
  todo campo de moeda é ISO-4217 de 3 letras, validado na borda (422 no corpo, 400 na query).
- **Revogar convite já aceito reescrevia o histórico** (o membro segue dentro, mas a trilha
  passava a dizer "revogado") e revogar um já revogado devolvia 200 → agora **409**.
- **Pagar parcela de financiamento `simulated` gerava despesa real** a partir de um cenário
  hipotético — e o Endividamento, que filtra `status == active`, não a explicava → agora **409**.
- **Logout não limpava o cache de queries**: os dados do usuário que saiu (extrato, dívidas,
  membros) ficavam em memória e apareciam para quem entrasse em seguida no mesmo navegador.
- **Filtro de categoria/tag sobrevivia à troca de workspace**, com IDs que não existem do
  outro lado: a lista voltava vazia e parecia que o workspace novo estava sem lançamentos.
- **`ruff check backend` estava vermelho** (import não usado numa migração), reprovando o
  primeiro passo do CI antes de qualquer teste rodar.

### Adicionado — auditoria 2026-07-29 (3ª rodada)

- **O formulário de despesa anuncia a fatura de destino** ("Vai para a fatura de Agosto/2026,
  vence 10/09"). A fatura é derivada no servidor (ADR 0002) por uma regra que a tela não
  contava — a partir do dia de fechamento a compra vai para o mês seguinte, e se aquela
  fatura já estiver fechada ela rola para frente —, então o usuário só descobria depois de
  salvar. Novo `GET /{ws}/credit-cards/{id}/statement-for?on=YYYY-MM-DD`, **só leitura**:
  perguntar não cria fatura.
- **O mês selecionado vive na URL** (`?month=YYYY-MM`) em Lançamentos, Rendas, Relatórios,
  Dívidas do mês e Endividamento: sobrevive ao reload e ao botão voltar, e dá para
  compartilhar o link de um mês específico.
- **Expurgo alcança `importrow`/`importbatch`** e apaga com `DELETE` em massa no banco, em vez
  de carregar milhões de linhas na memória do processo `cron`.

### Adicionado
- **Moeda estrangeira ponta a ponta**: lançamento, renda e recorrência em outra moeda são
  convertidos na entrada (PTAX oficial para as majores, fonte de mercado para o resto, + IOF de
  3,5% em compra no cartão), guardando o original para exibição. Store histórico de cotações
  (`ExchangeRate`) com backfill diário no serviço `cron` do Compose.
- **Moeda-base do workspace trocável pela interface**, com dry-run (quantas linhas, que
  cotações faltam) e reconversão de todo o histórico pela cotação da data de cada registro.
- **Panorama de endividamento** (`/liabilities`): financiamentos + faturas em aberto, no total,
  no mês e por pessoa — eixo separado do acerto entre membros.
- **Edição da compra parcelada inteira** (`PUT /transactions/{id}/installment-group`):
  refatiar total e número de parcelas de uma vez, congelando as já pagas.
- **Preview do lançamento** em qualquer tela (clique na linha abre o detalhe somente leitura).
- **Notificações no app** com consentimento no convite: quem já tem conta recebe um aviso para
  aceitar ou recusar, em vez de ser adicionado ao workspace sem saber.
- **Recorrência com intervalo** ("a cada N dias/semanas/meses/anos") e materialização
  preguiçosa: o que é recorrente aparece sozinho, sem depender de um botão.
- **Avisos de fatura** (fechada / vence em N dias / vencida) no cartão e na tela da fatura.
- **Filtros de categoria e tag** na lista de lançamentos; anexos podem ser escolhidos já na
  criação da despesa.
- **Convite pendente vira modal logo depois do onboarding.** Quem se cadastra por fora do
  link (ou entra com o Google, que não devolve o token) chegava ao app sem estar no
  workspace, com o convite só no sino — que é justamente o que ninguém olha no primeiro
  minuto de uso, e a impressão era de que o convite não tinha funcionado.

### Alterado — armazenamento de anexos
- **O conteúdo dos anexos saiu do banco para um volume** ([ADR 0007](docs/adr/0007-anexos-fora-do-banco-com-hash.md),
  desenho em [ADR 0016](docs/adr/0016-armazenamento-de-anexos-em-volume.md)). Recibo é dado
  grande, imutável e que nenhuma consulta lê: no banco, fazia cada dump carregar todos os
  comprovantes já enviados e obrigava a trazer o blob inteiro pelo driver para servir um
  arquivo. Os objetos são endereçados pelo `sha256` (o mesmo comprovante enviado duas vezes
  não duplica bytes) e a escrita é atômica.
- ⚠️ **O backup passou a ser DOIS artefatos**: o dump do Postgres **e** o volume
  `attachments_data`. Restaurar só o banco devolve os lançamentos com os recibos quebrados —
  ver [SETUP](SETUP.md#depois-de-subir).
- O diretório do volume é criado **na imagem** e pertence ao usuário do processo. Volume
  nomeado montado num caminho que não existe na imagem nasce `root`, e o backend roda como
  `appuser`: o primeiro upload de cada workspace levava "permission denied". Falha de
  gravação agora responde 503 com mensagem, não 500 — o erro acontecia no `mkdir`, que
  estava fora do bloco tratado. O `smoke_prod.py` passou a subir e baixar um anexo: é o
  único gate que exercita o volume real (os testes usam diretório temporário).
- ⚠️ **Quem já tinha anexos**: rode `scripts/migrate_attachments_to_disk.py` depois de subir.
  A migração de schema não move bytes de propósito (fazer isso a partir de um DDL destruiria
  recibos se o volume não estivesse montado), e o download serve dos dois lugares enquanto a
  transferência não acontece — sem janela de indisponibilidade.

### Corrigido — integridade financeira
- **Moeda-base diferente de BRL agora converte certo.** Toda entrada de valor usava a taxa
  `moeda → BRL` como se fosse `moeda → moeda-base`: num workspace em USD, uma despesa de
  EUR 50 era gravada como 315 USD, e uma em BRL virava o mesmo número em dólar (taxa 1,0).
  A taxa passou a ser a cruzada `(from→BRL)/(to→BRL)`, com fonte única em
  `ExchangeRateStore.rate_between` ([ADR 0015](docs/adr/0015-conversao-na-entrada-e-taxa-cruzada.md)).
- **Fim dos defaults de moeda fixos em "BRL".** Importação e criação em lote gravavam
  `currency="BRL"` literal — num workspace em outra moeda, cada linha importada caía fora de
  dívidas, relatórios, previsão e fatura, e sumia sem aviso. A moeda ausente agora vem do
  workspace (`resolve_currency`), com normalização de caixa; no frontend, de `useBaseCurrency()`.
- **Troca de moeda-base não encolhe mais item com quantidade.** Um item `3 × 20,00` era
  reduzido ao valor de UM unitário, quebrando `soma(itens) + ajustes == total` e o rateio das
  shares.
- **Busca no extrato ignora a caixa.** `LIKE` é case-sensitive no Postgres e insensitive no
  SQLite: procurar `supermercado` achava `Supermercado` em desenvolvimento e não achava em
  produção.
- **Financiamento nasce na moeda-base do workspace.** Era o último caminho de entrada com
  `"BRL"` fixo — o campo nem existia no corpo da criação. Num workspace em outra moeda, o
  financiamento ficava invisível no painel de Endividamento (que filtra pela moeda-base) e
  a despesa gerada ao pagar a parcela caía fora de dívidas, relatórios, previsão e fatura.
- **Receita do histórico de 6 meses respeita a moeda-base.** O card "Receita" já filtrava e
  o gráfico ao lado dele não: renda legada em outra moeda fazia os dois números discordarem
  para o mesmo mês, na mesma tela.
- **A previsão parou de contar os custos fixos duas vezes.** A média diária era calculada
  sobre TODO o gasto do mês, então um aluguel lançado no dia 1 era extrapolado pelos dias
  restantes — e ele já estava contado, no realizado ou nos fixos pendentes. Um aluguel de
  3.000 visto no dia 6 inflava a projeção em ~12.750. A tendência agora usa só gasto
  variável (fora recorrências e parcelas).
- **Estorno de parcela de financiamento vincula por ID.** O vínculo era o TÍTULO da despesa:
  renomear o financiamento deixava o gasto para sempre no caixa (com a parcela já reaberta), e
  uma despesa manual homônima era apagada junto.

### Corrigido — privacidade e segurança
- **Cadastrar-se não entra mais em workspace alheio.** O registro (e o login com Google)
  aceitava TODO convite pendente para aquele e-mail: quem soubesse o endereço de alguém dava a
  si mesmo acesso às finanças dessa pessoa — e vice-versa — sem ela aceitar nada. Agora só o
  convite cujo token acompanhou o cadastro (`/register?invite=…`, que a tela passou a ler) é
  aceito; os demais viram notificação com aceitar/recusar.
- **Anexo de despesa excluída libera a cota.** O recibo ficava inalcançável pela interface e
  mesmo assim ocupava os 200 MB do workspace, sem nenhuma tela por onde removê-lo
  ([ADR 0016](docs/adr/0016-armazenamento-de-anexos-em-volume.md)).

- **Revogar um convite encerra o aviso no app.** O convite pendente aparece como modal na
  primeira tela do convidado; revogado, o modal continuava lá com um "Aceitar" que só dava
  erro, e o contador de não lidas não tinha mais como zerar.

### Corrigido — experiência
- **Os meses dos gráficos de Relatórios voltaram ao português.** O nome vinha pronto do
  servidor, formatado pelo locale do processo — no container, "Jan/Feb/May" num app inteiro
  em PT-BR. O backend manda o mês (`YYYY-MM`) e quem desenha formata.
- **O convite pendente virou um diálogo de verdade** (foco preso, `Esc`, foco devolvido);
  era um overlay montado à mão, e é o primeiro modal que o usuário novo encontra.
- **Meses futuros acessíveis** em Lançamentos, Rendas e Relatórios: uma compra em 12x cria 11
  parcelas em meses à frente, e o seletor travava no mês corrente — enquanto "Dívidas do mês" e
  "Endividamento" já navegavam para frente e mostravam essas mesmas parcelas.
- **Mudar o dia de fechamento/vencimento do cartão atualiza a fatura em aberto** (as fechadas
  ficam congeladas, são histórico). Antes o aviso seguia anunciando a data antiga.
- Mensagens de erro do servidor deixaram de escrever `R$` fixo.
- A dica de câmbio no formulário estima na moeda-base do workspace, com a mesma taxa que o
  servidor vai aplicar.

### Alterado
- `notification.type` virou enum nativo no Postgres — o `alembic check` (gate de CI) acusava
  drift desde a introdução das notificações.
- Removida a coluna `transaction.card_limit_holder_user_id`, que nunca foi lida nem escrita.
- Painel de endividamento faz uma varredura de faturas por cartão em vez de duas.

## [4.0.0] — 2026-07-20

Primeira versão pública. Base completa da aplicação.

### Adicionado
- Workspaces com papéis (owner/admin/member/viewer) e convites por e-mail e por link.
- Despesas com divisão (igual/porcentagem/valor fixo) e **divisão por item** (quantidade × valor unitário).
- Ajustes de total (desconto, imposto, gorjeta, frete, cashback, arredondamento).
- Origem do pagamento por pagador (método + conta/carteira); múltiplos pagadores.
- Dívidas consolidadas e acertos validados (sem sobrepagamento).
- Cartões de crédito com ciclo de fatura (aberta→fechada→paga + reabertura), total congelado, limite comprometido e parcelamento coeso.
- Recorrências (diária/semanal/mensal/anual) com materialização completa e escopos de edição.
- Financiamentos SAC/PRICE por mês de calendário, com quitação antecipada simulada.
- Importação de CSV em lote, com decisão por linha e idempotência.
- Renda, orçamento por categoria e previsão de fim de mês.
- Atualização em tempo real por WebSocket, com sequência de integridade e resync.
- Autenticação por cookie HttpOnly com rotação de refresh e detecção de reuso, Google OAuth e reset de senha.
- Trilha de auditoria por workspace; hardening de produção (CSRF, rate limit, TrustedHost, CSP).
- Deploy via Docker Compose (nginx + backend + Postgres) e migrações Alembic.

### Integridade financeira
- Alocação monetária em centavos (sem parcela negativa; soma exata).
- Política única de status/moeda para todas as agregações.
- Atomicidade por requisição (um único commit).
- Fatura derivada no servidor; máquina de estados da despesa.

Decisões documentadas em [docs/adr/](docs/adr/README.md).
