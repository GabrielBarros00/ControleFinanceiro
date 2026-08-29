# Changelog

Todas as mudanças relevantes deste projeto são documentadas aqui.
O formato segue [Keep a Changelog](https://keepachangelog.com/pt-BR/1.1.0/) e o versionamento
segue [SemVer](https://semver.org/lang/pt-BR/).

> **Sobre a versão:** `APP_VERSION` (`backend/app/core/config.py`, hoje `4.0.0`) nomeia a
> LINHA do produto — é o "V4" do nome — e aparece no `/health` para identificar o binário
> em produção. Ainda não há release tagueada: tudo abaixo é o caminho até a 4.0.0 e vive em
> `[Não lançado]`. Ao cortar a primeira tag, mova este bloco para `## [4.0.0] - AAAA-MM-DD`.

## [Não lançado]

### O app passou a avisar antes de a conta vencer

Ele sabia o que você deve e quando, e não contava. As telas de Contas a pagar e
Compromissos são **puxadas**: só informam quem abre. Uma conta esquecida é a
falha mais cara que este app pode deixar acontecer, e é justamente a que ele
tinha todos os dados para evitar.

Agora avisa **três dias antes** (configurável), **no dia** e **uma vez** se
passar — cobrindo as três obrigações com data: conta a pagar, fatura de cartão e
parcela de financiamento. Notificar só conta a pagar entregaria algo que parece
completo e não é: o `payables_service` exclui compra no cartão de propósito, e a
fatura — a conta que mais dói esquecer — ficaria calada.

**Três marcos por conta é o teto.** Cada aviso a mais é fadiga, e fadiga
transforma notificação em ruído que a pessoa desliga — perdendo junto o aviso que
importava. Cinco contas vencendo viram **um** aviso, não cinco.

**A permissão se pede uma vez, e só depois de explicar.** `requestPermission()` é
irreversível na prática: negado, o navegador não pergunta de novo e o conserto
vira um caminho nas configurações que ninguém acha sozinho. Então primeiro
aparece um convite nosso, dizendo o que se ganha; o prompt do navegador só vem
depois do clique em "Ativar". Quem diz "agora não" não some: fica um botão ao
lado do sino e na tela de Contas a pagar, e o convite volta em uma semana.

**No iPhone, instalar deixou de ser opcional** — a Apple só entrega push para app
da Tela de Início. O app detecta o caso e ensina a instalar, em vez de oferecer
um botão que não pode funcionar.

O aviso **não mostra o valor** por padrão. O conteúdo trafega cifrado ponta a
ponta; a exposição real é a tela de bloqueio, onde qualquer um que olhe o
aparelho lê o que chegou (ADRs 0018 e 0021). Há preferência para incluir.

Sem chave VAPID configurada a funcionalidade **se desliga sozinha** em vez de
quebrar: o sino continua avisando. Ver [SETUP.md](SETUP.md) e o
[ADR 0033](docs/adr/0033-aviso-de-vencimento.md).

### Acertos: o saldo parou de parecer uma cobrança do mês

A tela de Acertos empilhava quatro coisas na mesma rolagem — o acumulado de
todos os meses, o retrato de um mês, as despesas que originaram a dívida e o
histórico de pagamentos — sem dizer qual era qual. O pior efeito era o número do
topo: "Saldo geral a acertar: R$ 320" lê-se como uma conta a pagar **agora**,
quando pode ser a soma de três meses que ninguém fechou. E o histórico aparecia
duas vezes, porque o retrato do mês repetia, logo acima da tabela, os mesmos
pagamentos que ela listava.

Investigando a confusão, apareceu a causa de fundo: **os dois números nunca
foram calculados do mesmo jeito**. O saldo geral soma todos os meses e desconta
todos os acertos; o do mês soma um `billing_month` e desconta só os acertos
marcados com ele. Como todo lançamento recebe `billing_month` automaticamente,
vale uma identidade exata — `saldo geral = Σ dos saldos mensais + acertos sem
mês` — que agora a tela mostra aberta, linha a linha, com o total fechando no
rodapé (`GET /{ws}/debts/by-month` e o par `/me/debts/by-month`). Meses além do
teto da lista viram uma linha somada em vez de sumirem: uma quebra que não fecha
é pior do que não existir. A identidade e as duas naturezas do acerto viraram o
**ADR 0031** — não eram comportamento novo, eram decisões que o modelo já tomava
e que ninguém havia escrito, e é por não estarem escritas que se perderam.

E apareceu um segundo achado, esse invisível havia tempo: **existem dois tipos de
acerto e nada os distinguia**. Registrar a partir de um mês grava
`billing_month` e fecha aquele mês; registrar a partir do saldo acumulado grava
`NULL` e abate o total sem fechar mês nenhum. O campo sempre veio na resposta —
faltava na tela, e faltava até no tipo do frontend, escrito à mão sem ele. É a
explicação do saldo que "caía sozinho". Agora cada acerto do histórico carrega
uma pílula com o mês que fecha, ou **"sem mês"**.

O resto é reorganização, no desktop e no celular:

- **Três abas** — Resumo, Por mês e Histórico —, com o estado em `?tab=`, então
  a aba entra no link e no botão voltar. O rótulo da aba passa a ser a resposta
  de escopo que faltava.
- **Uma linha por pessoa** no lugar dos dois cards "Você deve"/"Você recebe".
  Os rótulos repetiam os do topo, e dentro de um espaço um dos dois cards estava
  sempre vazio por construção — o pareamento põe cada pessoa em um lado só.
- Pela mesma razão, os três `StatTile` da tela do espaço viraram **um número e
  uma frase**: dois deles eram sempre zero, e "Saldo líquido" era só o sinal do
  que sobrava. (Na tela global os dois ficam: lá somam espaços distintos, e o
  ADR 0020 continua proibindo compensá-los.)
- **"Despesas do mês" nasce recolhida**, com o resumo na dobra (`56 · R$ …· 56
  em aberto`). É a justificativa da dívida, não a resposta da tela — e, na tela
  global, ela se repetia uma vez por espaço.
- O histórico virou **um lugar só**, com cartões no celular. As duas tabelas
  viviam no `overflow-auto` do `ui/table.tsx`, com a coluna de valor fora da
  tela.

O gate de 360px agora abre **todos** os blocos recolhidos antes de medir — e
falha se não achar nenhum para abrir, porque um portão que mede a tela dobrada
protege o nada. O scanner de acessibilidade percorre as três abas: o Radix
desmonta a aba inativa, e varrer só a inicial deixaria dois terços da tela sem
conferência. E um E2E novo (`e2e/acertos.spec.ts`) monta dois meses, um acerto de
mês e um de acumulado, e confere que **a soma das linhas exibidas é o total
exibido** — a identidade cobrada onde ela importa, na tela, atravessando rota,
serialização e `Intl`.

### Instalar o app deixou de ser um segredo (e o ícone com o Chrome no canto ganhou explicação)

O app é instalável desde sempre — manifesto, service worker, ícones, metas do
iOS. O que não existia era a **porta**: a oferta morava no fim de Configurações ›
Aparência, e ninguém chega lá por acaso.

Pior, ela estava morta. `beforeinstallprompt` dispara **uma vez por carregamento
de página**, cedo, e o Chrome não o repete em navegação de SPA. Como o listener
vivia dentro do hook — usado só por aquele cartão —, o evento chegava ainda em
`/login`, sem ninguém escutando, e o login navega client-side, sem reload. O
botão "Instalar" só aparecia para quem desse F5 **estando** em `/settings`. Nada
disso dava erro em log nenhum: a funcionalidade simplesmente não acontecia.

Agora a captura mora em escopo de módulo (`lib/install.ts`, chamada em
`main.tsx` antes do `createRoot`) e o convite fica na **barra superior**, em toda
tela — só o ícone no celular, ícone e rótulo a partir de 640px, e some sozinho
quando o app já está aberto em janela própria. No iPhone, onde não existe evento
de instalação, ele abre o caminho do Safari em vez de fingir que instala.

E o cartão de Configurações passou a **diagnosticar**, porque o mesmo manifesto
produz dois resultados diferentes no Android: instalar de verdade gera um
**WebAPK** (ícone limpo, app na lista do aparelho); quando a ponte com o Play
Services falha, ou quando a instalação partiu de "Adicionar à tela inicial" em
vez de "Instalar app", o Chrome cria um mero **atalho** — e o marca com o próprio
logo no canto do ícone. Nenhum código conserta isso: a decisão é do aparelho. O
que dá para fazer é dizer em qual dos dois estados a pessoa está, e agora o
cartão diz — se esta janela é o app, e se existe app instalado no aparelho
(`getInstalledRelatedApps()`, ligado pela entrada auto-referente em
`related_applications`) — com o passo a passo para refazer a instalação.

> **A palavra que apaga tudo:** `prefer_related_applications: true` no manifesto
> faz o Chrome parar de oferecer a instalação, em silêncio, e fica a um campo de
> distância do que foi acrescentado. O portão está no `verify-build-assets.mjs`,
> que roda a cada `npm run build`, e não só na suíte mobile.

### O dinheiro sai quando sai, não quando você anota

O app dizia que **toda** despesa fora do cartão saía do bolso no instante em que
era registrada. Pix, dinheiro, boleto, transferência: `payment_method` não entrava
em consulta nenhuma — era rótulo. O boleto que vence dia 10 debitava o caixa no
dia 10, pago ou não, e a conta de luz que a recorrência criava sozinha fazia o
mesmo, sem que ninguém tivesse afirmado nada. "Marcar como pago" não existia:
`status = paid` está na máquina de estados desde o começo e nenhuma rota nem tela
o escrevia. A pergunta "quanto ainda vai sair este mês" não tinha resposta.

Agora `Transaction.settled_at` diz quando o dinheiro saiu, e o caixa passa a
contar por ela. A conta de julho paga em 14 de agosto continua sendo gasto de
julho (consumo, dívidas, relatórios) e vira dinheiro que saiu em agosto, na
cotação daquele dia. O que ainda não foi pago vive em **Contas a pagar** — item
novo na navegação, em Pessoal e no espaço, com o que venceu em destaque e um botão
para confirmar várias contas de uma vez, informando o dia.

É opção do ESPAÇO ("Controlar o pagamento das contas", ligada por padrão): quem
lança tudo depois de pagar não quer a etapa a mais. A recorrência ganhou
"Pagamento automático" para o que o banco debita sozinho. E a migração preenche
`settled_at` de TODO o histórico — nenhum número de mês fechado muda. (ADR 0029)

> **O que muda para quem já usa.** Nada no passado. Daqui pra frente, a
> ocorrência que a recorrência criar nasce **a pagar** — é o defeito que o ADR
> corrige, e é onde ele mais aparece. Se o aluguel ou a internet saem por débito
> automático, ligue "Pagamento automático" no modelo e eles voltam a ir direto
> para o caixa. Lançamento digitado à mão continua nascendo pago (a data já
> chegou), então o dia a dia não ganha etapa nenhuma.

### Alterar a recorrência agora altera alguma coisa

Mudar "todo dia 5" para "todo dia 20" não movia os lançamentos já criados: eles
ficavam no dia 5, para sempre. Excluir o modelo não apagava nada; desativá-lo
deixava a conta do mês corrente contando. E a única opção que existia era um
`<select>` no rodapé de um modal longo, que não dizia quantos nem quais
lançamentos seriam atingidos. Somado ao "Seu mês" não materializar recorrência
nenhuma, a conclusão de que "alterar a recorrência não muda nada no Geral" estava
correta pelo que a tela mostrava.

Salvar agora abre uma **revisão**: a lista dos lançamentos afetados, o que
acontece com cada um (muda de data, atualiza, cancela, cria, ou "já paga — não
será alterada"), um filtro "aplicar a partir de", e uma caixa por linha. Nada é
aplicado sem estar marcado. Excluir e desativar passam pela mesma tela e oferecem
cancelar os que já existem. A lista sai da MESMA função que executa a escrita, e
as travas correm de novo no servidor — se alguém pagou a conta enquanto o diálogo
estava aberto, ela é recusada. (ADR 0030)

### Recorrência com fim, e parcelamento sem juros

Uma mensalidade de faculdade paga por doze anos era uma série infinita. A
recorrência ganhou "Termina": nunca, numa data, ou depois de N ocorrências — e a
lista passa a dizer "até 07/2038 · 87 de 144 restantes". Vale também para renda
(bolsa, aluguel recebido por prazo determinado). Séries encerradas param de gerar
sozinhas.

Para quem prefere acompanhar parcela a parcela, o formulário de financiamento
ganhou o modo **Parcelamento sem juros**: some a taxa, some SAC/PRICE, e o
cronograma vira "12× de R$ 1.200,00". O cálculo já suportava taxa zero; faltava a
porta de entrada — e o vocabulário certo, porque "Tabela PRICE" numa mensalidade é
linguagem de empréstimo para o que não é um. (ADR 0030)

### O espaço que ninguém podia apagar

Havia duas respostas para "de quem é este espaço", e nada as mantinha juntas: a
API **exibia** `created_by_user_id` (quem criou) enquanto quem **autoriza** é a
membership com papel `owner`. Coincidiam por construção no instante da criação e
por mais nenhum motivo.

Elas não divergiam na prática só porque a propriedade era um estado terminal: a
API recusa promover a `owner`, recusa alterar o papel de quem já é, recusa
removê-lo e recusa que ele saia. Somado a um `admin.py` que sequer importava
`Workspace`, desativar o dono produzia um espaço **permanentemente indelével** —
a única conta que poderia apagá-lo deixava de autenticar, ninguém podia herdar o
papel, e os dados seguiam vivos para os demais membros sem uma pessoa
responsável por eles.

Agora o dono sai da membership, que é a mesma linha que manda. `created_by_user_id`
fica como registro histórico e não é reescrito nem pela transferência: quem criou
continua tendo criado. Existe `POST .../members/{id}/transfer-ownership` — o alvo
vira dono, o antigo vira `admin` (perde o poder terminal, não o espaço) — e o
administrador de plataforma passa a receber **409** ao tentar desativar ou
remover quem ainda é dono de algo, com o nome do espaço e o caminho na mensagem.

A troca dos papéis é um `UPDATE ... WHERE role='owner'` com checagem de linhas
afetadas, não uma atribuição no ORM: duas transferências simultâneas do mesmo
dono liam ambas "sou owner" e produziriam **dois** donos.

E `member_count` parou de contar fantasmas: conta desativada ou excluída não é
uma das "3 pessoas" que a tela promete. O dono é a exceção deliberada — ele
aparece mesmo inativo, porque "de quem é" precisa de resposta, mas não entra na
contagem. Ver [ADR 0028](docs/adr/0028-propriedade-do-espaco-e-transferencia.md).

### O seletor que não dizia de quem era o espaço

`owner_name` viajava na resposta desde que o seletor existe e **nenhuma tela o
lia**: a lista dizia só "3 pessoas". Quem participa de dois espaços de nome
parecido não tinha como saber qual é o da Ana. Agora o rótulo é `De Ana Souza ·
3 pessoas`, ou `De você · só você` quando o espaço é seu — no seletor, na barra
lateral, na gaveta do celular e na lista de Configurações. Sem `owner_name`
(resposta antiga em cache), cai no rótulo de antes; nunca "De undefined".

### Um backend que pisca não expulsa mais ninguém do espaço

`useWorkspaces` devolvia `data ?? []`, e o `WorkspaceGuard` decidia olhando só o
tamanho da lista. Falha de rede chegava lá **indistinguível** de uma resposta
legítima vazia: a pessoa era levada para `/overview` com `replace`, sem mensagem
e sem o botão "voltar" desfazer. O hook passa a expor `isError`/`refetch` e o
guard mostra o erro com "tentar novamente" — só redireciona depois de uma
resposta que carregou. O arquivo não tinha teste nenhum; agora tem cinco.

### A importação que sumia quando o WebSocket não conectava

`use-imports.ts` era o **único** dos 19 hooks de mutação sem invalidação local —
dependia do evento voltar pela rede, contrariando a regra escrita em
`lib/ws-events.ts` ("sem depender da volta do evento pela rede"). Com o socket
bloqueado por infra ou ainda em backoff, a pessoa importava o extrato inteiro,
caía no Início e via os números de antes, sem nenhum sinal de que faltava algo.

### Toda rota passou a dizer o que devolve

Trinta e oito rotas respondiam um objeto sem forma declarada — nove com
`Dict[str, Any]`, o resto sem `response_model` nenhum, o que é pior: o
`api.gen.ts` recebia `unknown` puro. O frontend preenchia o vazio com interfaces
escritas à mão, e elas divergiam em silêncio — `use-monthly-debts.ts` dizia
`amount: number`, `DebtsPage.tsx` dizia `amount: string`, para o mesmo campo da
mesma entidade.

Agora todas têm schema, e `tests/api/test_openapi_sem_resposta_crua.py` reprova
qualquer nova — **sem allowlist**, porque uma exceção "temporária" é exatamente
como as nove nasceram. Ficam de fora só as três que não devolvem JSON: o
download de anexo e os dois redirecionamentos de OAuth.

Tipar já cobrou o que devia: as mutações de lançamento — o núcleo do app —
mandavam `Record<string, unknown>`, sem checagem alguma sobre o corpo; e um teste
de `/debts` afirmava sobre `{id, title, total_amount}`, a forma de um
*financiamento*, numa rota que sempre devolveu `{debtor_id, creditor_id, amount}`.
Passava porque não havia contrato com que divergir.

### Documentação que dizia o contrário do repositório

O README do estudo de redesign afirmava "**Nada aqui foi implementado**" enquanto
o roadmap ao lado registrava "Fases 0–5 implementadas e em produção", com 29 de
36 caixas marcadas e os artefatos em disco. Quem lesse o índice primeiro concluía
que o frontend inteiro estava por fazer — e o risco concreto era reimplementar o
que já existe. O README agora separa proposto, implementado e pendente, e aponta
o roadmap como fonte da verdade. Junto, o drift do próprio roadmap: ele falava em
Tailwind v3 e em estender `tailwind.config.js`, num projeto que está na v4, onde
esse arquivo não existe.

Também saíram cinco pacotes `@radix-ui/*` sem um único import (`avatar`, `label`,
`radio-group`, `scroll-area`, `select`) — instalados, auditados e enviados ao
bundler sem consumidor. Os três em uso ficam; a consolidação Base UI × Radix
segue diferida, como o roadmap já registrava.

### O botão que não dizia nada — e mandava dois convites

"Convidar" não dava sinal nenhum entre o clique e a resposta. Parecia que o
clique não tinha pego, a pessoa clicava de novo, e saíam dois convites.

**A causa não era aquele botão.** Os 19 hooks devolviam apenas o `mutateAsync`
de cada uma das 61 mutações e jogavam fora o `isPending` — a informação não
cruzava a fronteira do hook. Nenhum dos 149 botões do app tinha como saber que
havia ação em voo, mesmo que quisesse. Quatorze telas contornavam isso com um
`useState(false)` chamado `saving` ou `loading`, cada uma à sua maneira; o resto
não contornava.

Consertar botão a botão trataria os de hoje e deixaria o próximo nascer com o
mesmo defeito. **A trava passou a morar no `Button`**, por onde todos passam:
se o `onClick` devolve uma promessa, o botão se desabilita e mostra um spinner
até ela ASSENTAR — resolvida ou rejeitada. Rejeição que não destravasse deixaria
o botão morto até a próxima navegação, que é pior que o problema original. A
promessa segue para quem chamou; se o `Button` a engolisse, o `catch` que
levanta o toast de erro pararia de rodar.

São **duas** travas, e não uma. O `disabled` só vale depois do re-render; dois
cliques rápidos caem no mesmo ciclo do React e o segundo chega antes disso. A
trava por `ref` cobre essa janela.

O spinner é o aviso de "está acontecendo", e não um toast: um toast por ação
viraria ruído numa tela em que se apaga cinco lançamentos seguidos, e ainda
apareceria longe do dedo que clicou.

**O que o ponto único não alcança**, e foi tratado à mão:

- **`type="submit"`** — quem submete é o `<form>`, então o clique não roda
  handler nenhum que devolva promessa. Os nove ganharam `pending` explícito
  (`isSubmitting` do react-hook-form, ou o `isPending` da mutação). Dois estavam
  de fato desprotegidos: salvar recorrência e buscar pessoa no Admin.
- **Gatilhos que não podem virar `Button`** — "Marcar todas como lidas", "Sair
  da conta", o nome do anexo: `<button>` crus com estilo de link, que viram
  `<Button variant="link">` ao custo de quebrar a linha. Nasceu o `ActionLink`,
  que compartilha o COMPORTAMENTO (via `useAcaoPendente`) sem a aparência.
- **Excluir no extrato** trava a LINHA, não a lista — congelar todas faria uma
  exclusão lenta parecer a tela travada.

Uma armadilha de tipo, que é como a trava sumia sem ninguém ver: props escritas
como `onDelete?: () => void`. Um retorno `void` faz o TypeScript **aceitar** uma
promessa e o chamador descartá-la em silêncio. Onde o callback pode ser
assíncrono, o tipo virou `() => unknown`. Dois `onRetry={() => void refetch()}`
perderam o `void` pelo mesmo motivo.

Fecha com um **gate que lê os fontes**: nenhum `<Button type="submit">` pode
existir sem `pending`. É o único caminho que o ponto único não enxerga, é o
detalhe que ninguém lembra na próxima tela, e nenhum teste de comportamento o
pega — o formulário funciona, salva certo, e só falha quando alguém clica duas
vezes rápido.

### O e-mail bem formado continuou no spam — o que sobrou depois da forma

A rodada anterior corrigiu a forma da mensagem (`Date`, `Message-ID`, o corpo em
base64), foi para produção, e **os convites continuaram caindo no spam**. Vale
registrar o que a segunda investigação descartou, porque descartar custa tempo:

**O DNS está certo, e estes são os valores** — DKIM em
`resend._domainkey.notify`, SPF do envelope em `send.notify`
(`include:amazonses.com`, e não em `notify.`, que é o engano fácil), MX de
retorno em `feedback-smtp.sa-east-1.amazonses.com`, DMARC alinhando pelo domínio
organizacional. Autenticação inteira passando, de novo.

Sobraram três coisas, e nenhuma delas é a forma da mensagem:

1. **DMARC em `p=none`.** Nenhuma política aplicada. O filtro da Microsoft dá
   peso real a um domínio que se compromete com a própria autenticação, e é
   reputação que se compra de graça.
2. **O subdomínio de envio não tem MX nem A.** O `noreply@notify.…` é um buraco
   negro: responder a ele falha no DNS, e vários filtros checam se o domínio do
   remetente aceita alguma mensagem de volta.
3. **A forma do CORPO**, que é o que esta entrega resolve, abaixo.

### O e-mail deixa de ter a forma de um phishing

Mesmo bem formada, a mensagem era `text/plain` pura com uma URL de token solta
no meio do corpo. Essa é, literalmente, a forma de um phishing: texto curto, sem
identidade visual, e um link opaco pedindo que você clique. Nenhum produto
transacional real manda assim.

Agora toda mensagem sai como **`multipart/alternative`**, com as duas partes
geradas da MESMA chamada (`email_templates.corpo()`) — escrever os dois lados à
mão é como nasce o `MPART_ALT_DIFF`, a regra que pune quem mostra uma coisa a
quem lê HTML e outra a quem lê texto. O HTML **não pede nada a servidor nenhum**:
sem logo remoto, sem webfont, sem pixel de rastreio. O Outlook bloqueia imagem
externa por padrão, e o pedido a um terceiro no momento da leitura é sinal
negativo por si só. O botão é uma célula de tabela com `bgcolor`, e não um `<a>`
com `padding`, porque o Outlook para Windows renderiza com o motor do Word e
ignora `padding` em elemento inline. A URL completa aparece abaixo do botão como
link cujo texto visível é o próprio endereço — nenhuma âncora exibe um destino
diferente do que carrega.

Três cabeçalhos entraram junto:

- **`Reply-To`** (`EMAIL_REPLY_TO`, opcional; vazio omite o cabeçalho). Sem ele,
  quem responde a um convite fala com um endereço que não existe;
- **`Auto-Submitted: auto-generated`** (RFC 3834) e **`X-Auto-Response-Suppress`**,
  que impedem a resposta automática de férias de voltar para o `noreply@`. Cada
  ciclo desses é um bounce, e bounce gasta a reputação que este trabalho todo
  persegue.

**`List-Unsubscribe` ficou de fora de propósito.** Ele é de mala direta; estas
mensagens são transacionais, as regras de bulk sender do Gmail e do Yahoo as
isentam, e oferecer descadastro num "redefinir sua senha" sinaliza marketing ao
classificador.

`EMAIL_REPLY_TO` passa pela **mesma peneira** do `EMAIL_FROM` — o bloco virou o
helper `_endereco_unico` —, e `Subject` deixou de receber dado do usuário cru:
nome de espaço e nome de quem convida são escolhidos por quem usa, e um `\r\n`
no meio deles acrescentava cabeçalhos que ninguém escreveu. `EMAIL_FROM` era o
único campo com essa defesa declarada.

Sobre o `cte="quoted-printable"` das duas partes: ele é para o texto que ainda
vai ser escrito. Sem ele o `set_content` decide por heurística, e a decisão muda
com a proporção de acentos do corpo — pouco acento vira `quoted-printable`,
corpo muito acentuado vira `base64`. As mensagens de hoje caem no lado bom por
sorte, e alguém reescrevendo uma frase amanhã não deveria mudar a pasta em que o
e-mail cai.

### O celular ganha um app — e o app passa a dizer o que é seu e o que é do grupo

No celular faltavam duas coisas que não são detalhe: **saber onde você está** e
**poder sair de lá**. A separação entre a camada pessoal (`/me/*`, ADR 0021) e a
de um espaço compartilhado (`/w/:id/*`, ADR 0020) é sólida no servidor, mas vivia
só na barra lateral — que é `hidden md:flex`. Abaixo de 768px:

- a gaveta "Mais" chamava `navFlat()`, que **descarta os rótulos de seção**, e
  despejava quinze destinos numa grade sem hierarquia. "Acertos" e "Seus
  acertos", "Relatórios" e "Seus relatórios" apareciam lado a lado, mesmo ícone,
  mesma cor, e nada dizia qual era qual;
- **não havia como trocar de espaço.** O seletor só existia na barra lateral.
  Quem participa do próprio espaço e de mais um ficava preso naquele em que o
  app abriu;
- a barra superior tinha só o sino.

Agora existe um **seletor de escopo** (`ScopeSwitcher`) no topo do celular, que
sempre anuncia onde você está e abre a lista com "Pessoal" e todos os espaços —
o mesmo componente que o desktop passou a usar, incluindo a camada pessoal, que
o seletor antigo nem listava. A gaveta "Mais" voltou a ter seções (e passou a
mostrar "Administração" a quem tem o papel: a chamada omitia `isPlatformAdmin` e
o item nunca aparecia no celular).

**O vocabulário parou de falar quatro línguas.** Havia "Meu / Global / Seus /
pessoal" para uma ideia e "workspace / casa / espaço / o nome dele" para a outra
— com uma colisão literal no meio: toda conta nascia dona de um espaço chamado
"Meu Workspace", enquanto a seção chamada "Meu" significava justamente o que
**não** está em espaço nenhum. Passa a valer um par só, **Pessoal ×
Compartilhado**, e uma palavra só para o contêiner: **espaço**. "Visão global"
— que sugere "de todos" e significa "só meu" — virou **"Seu mês"**. Contas novas
nascem com "Meu espaço"; as existentes ficam como estão (o nome é editável).

**Quatro telas estouravam a largura do celular** e nenhum teste media isso — um
`grep` por `scrollWidth` no repositório voltava vazio, e o catálogo de capturas
cobria cinco rotas, nenhuma delas quebrada. O maior culpado era invisível: **todo
`<select>` do app usava `text-sm`**, e o Safari do iPhone dá zoom ao focar um
campo com fonte menor que 16px — e não desfaz. A partir do primeiro toque, o app
inteiro ficava grande e deslocado. Havia treze cópias da mesma constante de
estilo; agora há um `NativeSelect` só, com `text-base md:text-sm`.

O resto da varredura, tela por tela, nos dois temas, a 360/390/1440px:

- `PageHeader` com bloco de ação `shrink-0` sem `flex-wrap` (Rendas somava 490px
  numa faixa de 328px), `TabsList` sem rolagem (a aba "Orçamento" ficava
  literalmente cortada em Relatórios; `/admin` estourava 200px), `min-w-[300px]`
  do "Total da Fatura" dentro de um `Card` com `overflow-hidden` — o número mais
  importante da tela era o único inalcançável no celular;
- as cinco tabelas largas (amortização com 7 colunas, pessoas do `/admin` com 7,
  despesas do mês, rendas, recorrência) viram **cartões** abaixo de `sm`, por um
  padrão único (`CardsOrTable`), em vez de uma tira rolável em que a coluna de
  valor ficava fora da tela;
- filtros de Lançamentos e do Extrato viram uma **gaveta com contador**: eram
  210px e 260px de controles antes da primeira linha de dados;
- **safe-area** em toda parte (`viewport-fit=cover` + `env(safe-area-inset-*)`):
  a barra inferior e o rodapé dos diálogos ficavam sob o indicador de home do
  iPhone;
- "Agosto **De** 2026" — dois navegadores de mês aplicavam `capitalize` do CSS,
  que capitaliza cada palavra, sobre o rótulo do `Intl`. Quem capitaliza agora é
  o `monthLabel`, e o `PeriodPicker` deixou de ter uma cópia privada dele;
- alvos de toque: o "X" dos diálogos tinha **16×16px**, o menor botão do app.

**Dá para instalar como aplicativo.** Manifesto, ícones (192/512/maskable/apple,
gerados por script versionado a partir do PNG da marca) e um **service worker
escrito à mão** — sem Workbox, que traria uma árvore de dependências para gerar
60 linhas e esbarraria na CSP `default-src 'self'`. Ele guarda a casca para o app
abrir sem rede, e **nunca toca em `/api/`**: num app de dinheiro, saldo cacheado
é pior que saldo nenhum, porque aparece com cara de atual. Em Configurações →
Aparência há "Instalar aplicativo"; no iPhone, onde o evento de instalação não
existe, o cartão ensina o caminho do Safari em vez de oferecer um botão morto.

Os portões que faltavam: `mobile_layout.mobile.spec.ts` mede `scrollWidth` em
**todas** as rotas a 360px e nomeia o elemento culpado quando falha (conferido
falhando: `/me/income rola 163px`); `pwa.spec.ts` roda contra o nginx real e
pega um service worker que cacheie a API (conferido também: três URLs vazam e a
asserção quebra). O roteiro de capturas passou de 5 para 22 telas no celular.

### O e-mail descobre por qual porta sai — e a marca vira "Controle Financeiro"

Em produção, "enviar e-mail de teste" respondia `TimeoutError: timed out` vinte
segundos depois, e nada na tela dizia o que fazer com isso. A causa não estava na
configuração de e-mail: **o provedor do VPS bloqueia a SAÍDA em 25, 465 e 587**
(medida antispam padrão), enquanto o provedor de e-mail atendia normalmente em
2587 e 2465 — as portas alternativas que existem justamente por causa desse
bloqueio. Descobrir isso exigia adivinhar uma porta, reiniciar o stack e clicar de
novo, quantas vezes fossem necessárias.

Agora quem descobre é o backend, em `app/services/smtp_transport.py`: sonda as
portas do mesmo host **em paralelo** (587, 2587, 2525, 465, 2465, 25 — ~5s no
pior caso, não a soma dos timeouts), entrega pela primeira que completa o
handshake e **memoriza a rota** para os envios seguintes. STARTTLS e SSL
implícito passam a conviver, escolhidos pela porta e pelo que o servidor anuncia.
A tela de Administração mostra por onde o e-mail saiu, e o erro, quando há, vem
com o diagnóstico em vez do timeout cru.

Três fronteiras impedem que "tentar de novo" cause dano, e cada uma tem teste:

- **só falha de conexão troca de porta.** Senha recusada ou remetente não
  verificado é a mesma resposta em qualquer porta — repetir multiplicaria a
  rejeição no provedor. A distinção é sutil porque `smtplib.SMTPException` herda
  de `OSError`: um `except OSError` ingênuo tentaria cinco logins com a mesma
  credencial errada;
- **nada é reenviado depois do `DATA`.** Queda com a mensagem já entregue vira
  `EntregaIncerta`, não um e-mail duplicado;
- **falha total entra em espera de 60s.** SMTP fora do ar não pode custar a
  sondagem completa a cada convite. O botão de teste ignora a espera, porque quem
  clica nele acabou de mexer no firewall.

De quebra, credencial não trafega mais em claro: com senha configurada e STARTTLS
anunciado, o TLS sobe mesmo com `SMTP_TLS=False`; sem STARTTLS anunciado, a rota
é descartada em vez de degradada.

**A validação que recusava 465/2465 no boot saiu** — ela barrava exatamente as
portas alternativas de que um servidor com a saída bloqueada precisa, e um `.env`
correto derrubava o app no start.

**E, entregue, o e-mail caía no spam.** Com a autenticação inteira passando —
DKIM, SPF do subdomínio de envio e MX de feedback publicados e corretos —, a
mensagem em si saía malformada: sem `Date` (que a RFC 5322 lista como
OBRIGATÓRIO), sem `Message-ID`, e com o corpo inteiro em base64, escolha
automática do `set_content` para texto com acento — e todo corpo deste sistema
tem acento. `MISSING_DATE`, `MISSING_MID` e `MIME_BASE64_TEXT` são três regras de
filtro com nome próprio, e a soma decide a pasta mesmo com DMARC alinhado. O
`Message-ID` usa o domínio do remetente e não o padrão do `make_msgid`, que é o
hostname da máquina — dentro de um container, o ID aleatório do Docker. Nenhuma
outra rede pega este defeito: o SMTP aceita, o provedor entrega, a tela responde
"enviado"; ele só aparece na pasta de spam de quem recebeu.

Na mesma leva, a identidade visual: `CFv4 Pro` vira **Controle Financeiro** na
barra lateral e nas telas de entrada, com o ícone do produto no lugar do genérico,
favicon próprio (`.ico` + `.png`), `<title>` de verdade no lugar de "frontend" e
`lang="pt-BR"` no HTML.

### Acertos também na camada "Meu" — e a tela da casa passa a dizer que é da casa

Quem participa de duas casas não tinha onde perguntar **"com quem eu me acerto,
somando tudo?"**. Acertos era do workspace de ponta a ponta, e descobrir que se
deve 150 na Casa e se tem 80 a receber na Viagem exigia abrir cada uma e somar de
cabeça — a mesma lacuna que o ADR 0020 fechou para renda e resultado, e que ficou
aberta aqui. Nova tela **Meu › Seus acertos** (`/me/settlements`), com
`GET /me/debts`, `GET /me/debts/monthly` e `GET /me/settlements` ([ADR
0027](docs/adr/0027-acertos-na-camada-global.md)).

**As duas telas convivem, e a diferença não é o alcance — é o recorte.** A global
é sempre `involved_only`, inclusive para admin e owner: dívida entre TERCEIROS
continua sendo assunto da tela da casa, que é quem a mostra a quem tem acesso
completo. Mesmo par de "Seus relatórios" × "Relatórios". A tela do workspace
agora diz isso em voz alta — título `Acertos · {casa}`, subtítulo "Somente esta
casa" e link para a global —, porque sem isso quem tem duas casas lê os números
de uma como se fossem o total.

**Agrupa, nunca compensa.** Dever 100 na Casa e ter 100 a receber na Viagem não é
estar quitado: são pessoas e acordos diferentes. Por isso a tela global **não tem
"saldo líquido"**, só a pagar e a receber lado a lado. Dentro de cada casa o
líquido continua existindo, onde ele significa alguma coisa.

**A escrita não mudou de lugar.** `POST /workspaces/{ws}/settlements` segue sendo
o único caminho — é lá que vivem o teto e a direção do ADR 0009, a trava contra
sobrepagamento concorrente e o `publish_event`, que exige workspace. A tela
global manda o `workspace_id` da linha clicada, e o diálogo imprime o nome da
casa. É o que a distingue do "Nova despesa" ausente na Visão global: lá o destino
seria ambíguo, aqui ele vem da própria linha.

**Casa sem cotação aparece, em vez de sumir.** Cada grupo vem na moeda-base da
própria casa; só os totais do topo convertem, e o que fica de fora é listado
**nominalmente e com o valor na moeda dele**. O `/me/overview` derruba o
workspace inteiro e devolve só um contador — a regra do ADR 0006 é não somar o
que não converte, mas "você deve R$ 0,00" para quem deve USD 90 é o mesmo modo de
falha que o `or ZERO` já produziu uma vez.

**Auditoria da própria onda, quatro achados.** Três eram de comportamento e
tinham em comum o mesmo defeito de raciocínio — deduzir um fato de uma consulta
que responde outra pergunta:

- **O histórico chamava de "Casa removida" um workspace vivo.** Os nomes vinham
  da lista de casas de que sou membro HOJE, e sair de uma é permitido depois de
  quitar o saldo (`_ensure_no_open_balance`). Quem saísse via todo o histórico
  daquela casa com um rótulo falso e um link quebrado. Agora o nome vem de uma
  busca por ID — casa arquivada também mantém o nome, porque história não se
  reescreve (ADR 0023).
- **Quitar o mês fazia o retrato dele sumir.** A seção mensal vivia dentro do
  `if` do saldo consolidado, e `/me/debts` só lista casa COM saldo pendente.
  Pagar tudo apagava da tela as despesas e o "tudo acertado ✅" — justamente a
  confirmação que a pessoa foi procurar depois de pagar.
- **`/me/debts/monthly` aceitava `?currency=` e devolvia o código sem converter
  nada** — um campo dizendo "estes números estão em USD" sobre valores em BRL.
  Removido: cada seção é uma casa, na moeda dela, e não há total a converter.

O quarto: o histórico global truncava em 50 sem dizer. Agora devolve `total` e a
tela avisa quantos ficaram de fora — truncar histórico financeiro em silêncio é o
mesmo modo de falha do `or ZERO`.

**Layout:** "EM ABERTO" quebrava em duas linhas na tabela de despesas. Um título
longo estica a primeira coluna, e sem largura fixa nas duas últimas o algoritmo
de tabela espremia o status até partir o fundo arredondado do badge ao meio.
Larguras fixas + `whitespace-nowrap` no status, no valor e na data.

Sem duplicação de lógica: `PersonalDebtService` compõe o `DebtService` de sempre,
`MonthlyLedgerBody` e `BalanceCards` saíram das telas da casa para servirem às
duas, e `OverviewService._workspaces_do_usuario` virou
`query_policy.workspaces_do_usuario` — três serviços precisam do mesmo recorte, e
a terceira cópia seria a chance de um deles esquecer o `deleted_at`. As famílias
novas entram em `GLOBAIS` no `ws-events.ts`: `['me-debts', 7]` não casa com
`['me-debts']`, que foi o defeito da Onda 6.

### Catálogo de telas: previews que dá para ver, e uma compressão reproduzível

As capturas eram de **página inteira**: a tela de Acertos saía 1440×5118, uma
tira de 3,5:1 que o GitHub renderiza como um risco ilegível na tabela do
catálogo. Agora é o VIEWPORT — 1440×900 no desktop, 390×844 no mobile (o viewport
CSS do iPhone 12–16 base). Não 1920×1080 porque o conteúdo do `AppShell` para em
`max-w-[1200px]`: numa janela maior as imagens só ganhariam vazio nas laterais.

E a recompressão para 256 cores, que sempre foi um passo manual dependente de ter
ImageMagick ou Pillow na máquina, virou `frontend/scripts/comprimir-shots.py` —
biblioteca padrão só, com `--check`. Numa regeração feita sem essas ferramentas
as imagens entraram cruas e `docs/images` cresceu 45% sem que nada acusasse; um
passo de release que ninguém consegue repetir não é um passo. Somados os dois,
o catálogo caiu de 4,6 MB para 2,1 MB com mais duas telas dentro.

### Auditoria de rendimento decrescente: a barra final, a tela que ninguém escaneou

Quarta e última passada, nos ângulos que a terceira apontou como sobra:
acessibilidade além do que o axe já cobria, comportamento com a infraestrutura em
volta quebrada, e carga.

**Duas coleções só respondiam COM a barra final.** `GET`/`POST /workspaces` e
`GET`/`POST /workspaces/{id}/transactions` — listar e criar workspace, listar e
criar lançamento, ou seja as quatro chamadas mais usadas do app. Sem a rota irmã,
a forma sem barra (a natural, a que qualquer cliente escreve) cai no
redirecionamento 307 do Starlette, e **nesse salto o cookie de sessão não
acompanha**: a resposta é 401. O projeto já tinha eliminado isso em
`me_accounts`, `me_cards`, `me_financing`, `me_income` e `admin` com o `_colecao`
deles; estas duas ficaram para trás. Apareceu por acidente — um teste de
resiliência escrito com a URL sem barra levou 401 onde esperava 200.

O alias entra **fora do schema** de propósito: o `openapi.json` já documenta a
forma com barra e o frontend foi escrito contra ela, então manter o schema
intacto evita regerar `api.gen.ts` por uma correção que não muda contrato nenhum.
O teste que blinda isso é uma varredura, e a pergunta dela é estreita — não "toda
rota aceita as duas formas" (`/health` e `/auth/login` nascem sem barra e ninguém
os chama com ela), e sim "existe rota que só responde COM barra?".

**A tela de Administração nunca tinha sido escaneada.** É a mais nova (ADR 0026)
e a mais densa em controle — seis abas, tabelas de pessoas, formulário de
configuração, convites e trilha —, e ficava de fora porque não havia caminho de
teste para ela: `/admin` exige superadministrador. Agora o backend do e2e sobe
com `SUPERADMIN_EMAIL`, a janela de bootstrap cria a conta, e o axe varre as seis
abas. **Zero violações WCAG 2 A/AA** — a tela nasceu correta, o que faltava era a
prova.

**A infraestrutura em volta quebrada não derruba nada** — e agora tem teste. Três
promessas estavam escritas em docstring e não eram exercitadas por ninguém: que o
e-mail é best-effort (SMTP recusando conexão não pode derrubar a emissão de um
convite, nem denunciar pelo erro quais endereços existem), que falha ao gravar
anexo vira 503 **sem deixar linha órfã** apontando para arquivo inexistente, e
que o `raise_on_error` só vale para o diagnóstico da tela de Admin. As três se
sustentaram com o serviço externo quebrado por `monkeypatch`.

**Carga ficou de fora, e por decisão.** O que dá para afirmar é o que
`tests/concurrency/` já mede: 14 invariantes sob 8 requisições simultâneas. Um
teste de carga de verdade precisa de infraestrutura própria e mede capacidade —
outra pergunta, e não a que uma auditoria de correção responde. Para um app de
família num deploy caseiro, não é o próximo risco.

**Sobre o método, de novo.** O teste novo de `/admin` reprovou três vezes por
motivos que não eram do app: timeout curto, depois um diagnóstico mal escrito, e
por fim o modal de onboarding aberto por cima — o Radix marca o resto da página
com `aria-hidden`, o `h1` some da árvore de acessibilidade e o `getByRole`
responde "element(s) not found" numa página que o snapshot mostra inteira. Foi
preciso ler o `error-context.md` do Playwright para ver o que estava na tela.
Vale o registro: quando um teste falha, a primeira hipótese a descartar é a de
que o teste está errado.

### Auditoria da matemática: o cronograma que não fechava e os 500 que o usuário disparava

Terceira passada, virada para o que as duas anteriores não olharam: a aritmética
do domínio, a privacidade sondada ATIVAMENTE e o comportamento diante de entrada
extrema. A verificação foi por força bruta, não por amostragem — 36.200
alocações de dinheiro e 2.800 cronogramas de amortização conferidos contra as
invariantes que eles próprios prometem.

**O cronograma de amortização produzia parcela negativa.** O SAC calculava a cota
`total/n`, arredondava UMA vez e repetia; quando esse arredondamento subia, as
`n-1` primeiras parcelas consumiam mais que o principal e a última — que recebe
"o que sobrou" — nascia **negativa**. R$ 10,00 em 600x terminava com uma parcela
de `-1,98` (juros `-0,02`, total `-2,00`). A tela não denunciava porque a linha
do saldo é `max(0, saldo)`: aparecia uma parcela de valor negativo com saldo
zerado. Agora a coluna de amortização é alocada em **centavos** por
`Money.split_equal` — a mesma primitiva que divide uma despesa entre pessoas, e
pelo mesmo motivo (ADR 0001). "Amortização constante" com granularidade de
centavo é isto: parcelas que diferem em no máximo um centavo, somando exatamente
o principal. No PRICE, onde a cota varia por período e `split_equal` não se
aplica, a amortização passou a ser limitada pelo saldo.

**E a criação de financiamento respondia 500.** `interest_rate` não tinha teto no
schema. Com juros altos, a PMT arredondada não cobre os juros do período, a
amortização fica negativa, o saldo CRESCE composto e algumas dezenas de períodos
depois estoura o contexto do `Decimal` — `InvalidOperation`, que sobe como 500.
Medido: R$ 12.345,67 a 0,5 a.m. em 360x. Agora o domínio recusa com 422 e diz o
motivo ("a prestação não cobre nem os juros do mês").

**Qualquer id acima de 64 bits derrubava a requisição.** `int` do Python não tem
teto; a coluna tem. `GET /workspaces/1/transactions/99999999999999999999` chegava
intacto pelo Pydantic e estourava no driver — `OverflowError` no SQLite,
`NumericValueOutOfRange` (embrulhado em `DataError`) no Postgres —, os dois
virando **500**. Não é vazamento nem corrupção: é o servidor assumindo a culpa
por um número que qualquer pessoa digita na barra de endereços, e um alerta de
erro em produção para cada tentativa. Tratado num lugar só, porque a semântica é
uma: são ~50 assinaturas com `id: int`, e espalhar `le=2**63-1` por cada uma
seriam cinquenta oportunidades de esquecer a próxima.

**O que a varredura NÃO achou** — e essa metade importa tanto quanto:

- **Privacidade**: uma sonda ativa põe um membro `involved_only` para varrer
  todas as rotas GET procurando os marcadores do lançamento, da renda, do cartão
  e do financiamento de quem divide a casa com ele. Zero vazamentos. O teste
  carrega o próprio CONTROLE: a mesma varredura, com o cookie da dona dos dados,
  precisa ENCONTRAR os marcadores — senão estaria passando por não medir nada.
- **Soft-delete**: um lançamento excluído aparecia em 5 agregados e some dos 5.
- **Dinheiro**: nenhuma divisão perde ou cria centavo em 36.200 combinações.
  (`split_by_percentages` aceitava `[200, -100]` — soma 100 e devolve cota
  negativa. O schema da API já barra com `0 < pct <= 100`, então era inalcançável;
  a mesma regra passou a valer no domínio, onde a classe se defende sozinha.)
- **500 por entrada**: fora o caso do id, nenhuma das ~400 requisições com valores
  extremos em campos numéricos derrubou rota nenhuma.

**A armadilha metodológica desta rodada.** A primeira versão da varredura de 500
acusou **106** respostas 5xx. Nenhuma existia: a suíte compartilha UMA sessão
entre requisições (`override_get_session`), e o primeiro erro de integridade a
deixa marcada para rollback — daí em diante toda chamada morre com
`PendingRollbackError`. Em produção cada requisição abre a própria sessão. Com o
`rollback()` entre chamadas, 106 viraram **1**, e esse era real. Vale como aviso:
um teste que acusa demais é tão suspeito quanto um que nunca acusa.

### Auditoria geral: sete tetos que não seguravam, e um deploy que não subia

Varredura completa do projeto com todos os portões verdes — 2536 testes de
backend no SQLite, 340 de frontend, ruff, eslint, typecheck, build, `alembic
check`, os 78 passos do smoke de produção contra a stack real do Compose, as 9
telas do `e2e-prod` e os 18 do `e2e`. Nenhum deles reprovava. Também não
reprovavam: as 147 rotas da API (nenhuma sem guarda de autenticação além das 11
públicas por projeto), o contrato entre frontend e backend (125 chamadas, todas
existentes), a ausência de `float` em caminho de dinheiro e a ausência de segredo
versionado.

Os sete defeitos encontrados são **o mesmo defeito sete vezes**: uma leitura que
agrega (dívida líquida, bytes usados, fingerprints já importados, usos de um
convite, superadmins restantes), um `if` que decide, e uma escrita que executa —
com nada segurando o intervalo entre a leitura e a escrita. Sequencialmente os
sete estavam certos; é por isso que a suíte inteira passava.

Medidos, um por um, contra Postgres com 8 requisições simultâneas:

| Invariante | Prometido | Medido antes |
|---|---|---|
| Acerto de dívida (ADR 0009) | ≤ R$ 500 | **R$ 4.000** (R$ 3.500 de crédito artificial) |
| Idempotência da importação (ADR 0008) | 1 lançamento | **8 lançamentos** |
| Cota de anexos (ADR 0007) | 1 MB | **2,4 MB** |
| Convite de cadastro (ADR 0026) | 1 conta | **8 contas** |
| Convite de workspace (ADR 0018) | 1 membro | **8 membros** |
| Último superadministrador (ADR 0026) | ≥ 1 | **0** |
| Cota mensal de convites (ADR 0026) | 3 convites | **8** |

O mecanismo de correção agora tem um lugar só, `app/db/locks.py`, com a razão de
cada alternativa descartada escrita ali: `SELECT ... FOR UPDATE` some em silêncio
no SQLite, `INSERT ... SELECT` com validação no `WHERE` não enxerga a escrita não
commitada da concorrente, e o `UPDATE` condicional resolve CONTADOR mas não
invariante sobre várias linhas. O preço assumido é que duas escritas simultâneas
no mesmo workspace passam a se enfileirar.

**O achado sobre teste, que vale mais que os seis.** O convite de workspace já
tinha o incremento atômico e um teste verde sobre ele —
`test_convite_por_link_respeita_max_uses` exercitava o *padrão* de UPDATE
isolado e provava que cada thread recebe um valor distinto. Verdade, e
irrelevante: a rota nunca olhava o valor recebido, então oito pessoas entravam
por um link de uso único com o contador registrando a verdade. Incremento atômico
**sem recusa** não limita nada. E o teste do último superadmin **passou na suíte
cheia e falhou sozinho** — sob carga o escalonamento entregou justamente o
interleaving que esconde o defeito. Um teste de concorrência verde não prova nada
até ser rodado isolado e repetido.

**O acerto de dívida era o mais caro.** `DebtService` soma pagos, devidos e
acertos anteriores; a rota compara o valor com esse saldo e insere. Oito
quitações simultâneas da dívida inteira leem o mesmo saldo e passam todas — R$
4.000 registrados contra uma dívida de R$ 500, e o devedor aparecendo como credor
de R$ 3.500. É a inversão de relação que o ADR 0009 nomeia como o motivo de o
teto existir.

**A importação duplicava o extrato inteiro.** A idempotência do ADR 0008 é um
`set` de fingerprints lido antes do laço que insere; dois envios simultâneos leem
o mesmo conjunto e inserem os dois. `ImportRow.fingerprint` tem índice, mas não é
único, então nada no banco recusa. O gatilho realista não é ataque nenhum — é o
duplo clique no botão de confirmar.

**A cota de anexos não era teto.** `_ensure_quota` soma os bytes já usados e
decide; o INSERT vem depois. 2,4 MB gravados numa cota de 1 MB — e "sem quota,
qualquer membro enche o volume" é a frase que a própria função usa para explicar
por que existe.

**Um convite de cadastro de uso único fazia nascer oito contas.**
`consome_convite` gravava `convite.uses += 1` em Python — exatamente o padrão que
o cabeçalho de `tests/concurrency/` nomeia como a classe de bug do projeto, e que
`members.accept_invite` já tinha corrigido para o `WorkspaceInvite`. A tabela do
ADR 0026 é nova, e a correção não veio junto. Num site `invite_only` — o padrão —
esse contador é o que decide **quem pode existir no servidor**.

**O convite de workspace tinha o incremento atômico e mesmo assim admitia todo
mundo** (ver acima: o `where`, e não o incremento, é o que recusa).

**Rebaixar dois superadministradores ao mesmo tempo deixava o site sem nenhum.**
Cada requisição contava os OUTROS e via um sobrar. Aqui o `UPDATE` condicional
sobre o alvo não resolve — a condição seria avaliada contra o snapshot commitado,
onde o outro ainda é superadmin —, então a trava cobre o conjunto inteiro de
superadmins e o "exceto" é aplicado depois, em Python: travar já excluindo o alvo
faria cada requisição travar um conjunto diferente, que não serializa nada.

**A cota mensal de convites** é a mais branda das sete e entrou por completude:
sem trava ela degradava para "teto + rajada" (a rodada seguinte já enxerga o
excesso e barra) em vez de cair de vez. Mecanismo idêntico, uma linha para
fechar.

#### E dois defeitos no caminho do deploy, que só aparecem na máquina lenta

**`docker compose up -d` falhava na PRIMEIRA subida.** O healthcheck do Postgres
era `pg_isready` sem `-h`, e por isso falava pelo **socket Unix**. Na primeira
subida o entrypoint da imagem roda o `initdb` e levanta um servidor TEMPORÁRIO só
nesse socket para inicializar o cluster — o `pg_isready` responde "aceitando
conexões", o compose marca o `db` como `healthy`, o backend começa o `alembic
upgrade head` e leva `FATAL: the database system is starting up`. O backend
entrava em laço de reinício, era marcado `unhealthy` e derrubava `frontend` e
`cron` junto: `dependency failed to start`.

Reproduzido com `down -v` seguido de `up`. Some em máquina rápida — que é por
que o `prod-stack` do CI nunca o viu — e aparece na lenta, que é a máquina de um
deploy caseiro, e no primeiro contato de quem seguiu o `SETUP.md`. O `-h
127.0.0.1` faz a checagem passar pelo TCP, que é exatamente por onde o backend
conecta. Junto veio um `start_period: 90s` no backend: numa base nova são dezenas
de revisões antes de o uvicorn abrir a porta, e sem ele cada falha desse
intervalo consumia uma das dez tentativas do healthcheck.

**A suíte `e2e-prod` deixava o cadastro ABERTO.** O `global-setup` grava
`registration_mode=open` pela API de admin para poder criar usuários, e não
devolvia nada. É uma linha no banco, que vence o `.env` (cascata do ADR 0026) e
sobrevive ao `docker compose down`. No CI não aparecia porque o `smoke_prod.py`
— que é quem confere o portão — roda ANTES, num volume novo; rodar os dois gates
de novo contra o mesmo stack já reprovava. E o `E2E_BASE_URL` existe justamente
para apontar a suíte a outro deploy: fazê-lo abriria o cadastro dele. Agora o
setup lê o valor vigente e o devolve num teardown.

Os sete ficaram cobertos por testes no leg `backend-postgres` do CI, onde o MVCC
os torna observáveis; no SQLite continuam invisíveis, porque um escritor por vez
mascara todos. São 14 invariantes em `tests/concurrency/` agora, e cada teste novo foi conferido
com a trava DESLIGADA antes de entrar — um teste de concorrência que nunca se viu
falhar não é prova de nada.

### Administração do site: a porta que estava aberta, e o poder que faltava

Duas ausências que só apareceram quando o deploy virou assunto concreto.

A primeira era um defeito: **`POST /auth/register` era aberto**. Publicado na
internet, qualquer pessoa que alcançasse a URL criaria conta no servidor. O rate
limit por IP atrasa um cadastro em massa; não impede ninguém de entrar.

A segunda era um buraco de projeto: o sistema sabia falar de papéis **dentro de
um workspace** e não tinha nenhuma resposta para *quem opera o servidor*.
Desativar uma conta, ler a trilha inteira, mudar um limite ou fechar o cadastro
exigiam `docker compose exec` e SQL na mão.

**O que entrou** ([ADR 0026](docs/adr/0026-papel-de-plataforma-e-cadastro-por-convite.md)):

- `User.platform_role` (`user` < `admin` < `superadmin`), eixo separado do papel
  de workspace. `access_policy` **não o consulta** — ser dono do servidor não
  abre um único lançamento alheio.
- Cadastro por convite como padrão, com duas espécies de token aceitas (o novo
  `RegistrationInvite` e o `WorkspaceInvite` que já existia) e uma **janela de
  bootstrap** para o `SUPERADMIN_EMAIL`, que fecha sozinha depois da primeira
  conta. Sem ela, um deploy novo seria um impasse: cadastro fechado e ninguém
  para convidar.
- Configuração em runtime (`AppSetting`) com cascata `banco → .env → embutido`.
  Ausência de linha significa "acompanhe o ambiente" — semear a tabela
  transformaria o `.env` em decoração.
- Modo manutenção que libera `/health`, `/auth/*` e `/admin/*`, para o
  administrador não se trancar do lado de fora.
- Tela `/admin` com visão geral, pessoas (uso por pessoa), convites,
  configurações, saúde e auditoria global.

**As travas, que vieram de cicatriz.** Na Onda 10 um rebaixamento de admin
*ampliava* a visão de quem era rebaixado. Aqui: admin não age sobre superadmin
nem promove a superadmin; e o **último superadministrador ativo** não pode ser
rebaixado, desativado nem removido — nem por ele mesmo. Sem superadmin, a
configuração vira imutável e o convite fica sem quem o emita.

**O que sustenta a promessa de privacidade.**
`tests/security/test_admin_sem_vazamento_financeiro.py` planta um lançamento com
valor, título e categoria improváveis e varre a resposta inteira de cada rota
administrativa procurando os três. Um `SUM` sobre coluna de dinheiro em
`/admin/overview` reprova ali — foi verificado introduzindo o vazamento de
propósito e confirmando que o teste o pega. A fronteira em uma frase:
**`COUNT(*)` é operação, `SUM(amount)` é intimidade.**

**Detalhes que a onda também corrigiu:**

- `SMTP_TLS` estava documentado no `.env.example` e no `SETUP.md`, era lido pelo
  `Settings` — e **não era passado pelo `docker-compose.yml`**. Quem precisasse
  de `False` preenchia o campo e nada acontecia.
- `BIND_ADDR` novo: a porta do Compose abria em `0.0.0.0`, então um deploy com
  Caddy terminando TLS continuava respondendo em `http://` na porta direta. O
  cookie `Secure` viajava numa conexão que não era segura.
- O rate limiter passou a ler o teto em runtime — e a leitura é **defensiva**: os
  baldes viraram dependência de `/auth/login`, e uma tabela ausente ou um
  Postgres momentaneamente fora do ar não podem transformar "não sei o teto" em
  500 na tela de entrada.
- `POST /auth/registration-policy` (público) para a tela de cadastro dizer "é só
  por convite" **antes** de a pessoa preencher o formulário inteiro.

### A auditoria da auditoria: a segunda porta era a do convite

Reauditoria da onda de administração. As dez correções anteriores estavam
corretas e bem testadas — mas a **lição** que aquela auditoria escreveu ("ao
fechar uma porta, procure TODA superfície que cria o recurso") tinha sido
aplicada a uma capacidade só.

**`assert_pode_convidar` também tinha um único ponto de chamada.** Um
`WorkspaceInvite` autoriza criar conta no site exatamente como um
`RegistrationInvite`, e as duas rotas que o emitem
(`POST /workspaces/{id}/invites` e `.../invites/link`) não consultavam nada. Como
todo usuário nasce `owner` do próprio "Meu Workspace",
`who_can_invite=admins_only` não valia nada: bastava convidar pela tela de
membros, sem cota. E `max_uses` não tinha teto — um link de workspace com
`max_uses=999999` era um cadastro público para o site inteiro, válido por até 30
dias, emitido por qualquer pessoa. O portão passou a valer nas três rotas, e a
cota conta as duas espécies; só entra na conta o convite que pode fazer o site
**crescer**, porque chamar para a sua casa quem já tem conta não cria conta
nenhuma.

**O cadastro continuava acontecendo durante a manutenção.** O middleware libera
`/auth/*` para o administrador conseguir entrar e desligar o modo; o cadastro
passava de carona, e um site em `registration_mode=open` seguia fazendo nascer
usuário, workspace e categorias semeadas — para a pessoa entrar e receber 503 em
tudo que importa. Quem recusa agora é `assert_pode_cadastrar`, com a janela de
bootstrap isenta: `maintenance_mode` é uma linha no banco e sobrevive a um
`down`, então um deploy que subisse com ela ligada trancaria o próprio dono do
lado de fora.

**`make backend-test` nunca rodou** — desde o primeiro commit, e falhava por dois
motivos empilhados: `tests/` não é pacote (então `import app` morria) e
`Settings` tem `env_file=".env"` relativo ao processo, de modo que rodar da raiz
lia o `.env` do *deploy* e o `extra_forbidden` do pydantic derrubava a coleção.
Só o `ci.yml` acertava, por acidente. O `pythonpath` no `backend/pyproject.toml`
resolve o primeiro para qualquer invocação e o alvo passou a rodar de dentro de
`backend/`, como o `migrate` já fazia.

- **O callback do Google não tinha rate limit.** Enquanto ele só autenticava,
  o balde do `/auth/register` bastava; desde que virou superfície de cadastro,
  deixar uma das duas portas sem teto por IP é a assimetria que o portão existe
  para não ter. Responde por redirecionamento, não com 429 em JSON: é uma
  navegação, e o corpo do erro apareceria na barra de endereços.
- **Rebaixar-se era permitido no servidor e a tela não oferecia** — o mesmo
  "servidor aceita, tela não oferece" que a auditoria anterior corrigiu duas
  linhas acima, na mesma tabela. O ADR justifica o auto-rebaixamento como a
  forma de um superadministrador passar o bastão, e ele só era alcançável pela
  API na mão. Agora o seletor aparece na própria linha, com confirmação: não tem
  volta sem outra pessoa. O interruptor de ativação continua fora de alcance.
- **`sobrescrito` respondia a outra pergunta.** Era "existe linha no banco", e a
  tela precisa de "o banco é quem manda": quando `get` descarta a linha — valor
  corrompido, ou um `IMPORT_MAX_ROWS` que baixou abaixo do que estava gravado —,
  o valor exibido vinha do ambiente com a marca de "gravado aqui", e o operador
  ia procurar a causa no lugar errado.
- `ATTACHMENT_QUOTA_BYTES` e `IMPORT_MAX_ROWS` faltavam no
  `backend/.env.example`; o `test_compose_env.py` só lê o `docker-compose.yml`.

### A auditoria da administração: a porta dos fundos e o primeiro acesso impossível

Auditoria da onda acima. Os portões estavam todos verdes — 2489 testes de
backend, 319 de frontend, lint, typecheck, build, `alembic check` — e mesmo assim
os dois defeitos mais graves eram **a promessa central da onda, pela metade**.

**O cadastro continuava aberto pelo Google.** `assert_pode_cadastrar` tinha um
único ponto de chamada: `POST /auth/register`. O callback do OAuth criava usuário
sem consultá-lo, então um deploy com Google configurado seguia aceitando qualquer
pessoa que tivesse uma conta Google e alcançasse a URL — inclusive com o cadastro
`closed`, e inclusive durante o modo manutenção, que libera `/auth/*`. Agora o
callback passa pelo mesmo portão, o convite viaja **assinado dentro do `state`**
do OAuth (o Google não devolve query string nossa) e a janela de bootstrap vale
também ali: o `SUPERADMIN_EMAIL` pode ser um endereço do Google.

**O primeiro acesso era impossível pelo navegador.** Num deploy novo o modo é
`invite_only`, ninguém tem convite e não existe quem o emita — e a tela de
cadastro escondia o formulário exatamente nesse estado. O SETUP.md mandava, em
dois lugares, ir a `/register` e cadastrar-se com o `SUPERADMIN_EMAIL`; não
havia como. Escapou porque **a tela de cadastro não tinha um único teste**, e
porque o `smoke_prod.py` e o `global-setup.ts` do e2e se cadastram pela API — os
dois portões automáticos passam ao largo dela. `registration-policy` agora
publica `primeiro_acesso`, a tela se anuncia como "Primeiro acesso" enquanto o
site não tem dono, e `RegisterPage.test.tsx` cobre os seis estados do portão.

**O resto do que a auditoria encontrou:**

- **Busca de pessoas tratava `%` e `_` como curinga.** `/admin/users?busca=%`
  devolvia a lista inteira. Não é injeção — o valor é parametrizado —, é um
  filtro que responde outra pergunta, e o projeto já tinha resolvido isso na
  busca de lançamentos com `autoescape=True`.
- **`import_max_rows` podia ser gravado acima do teto que vale.** A tela aceitava
  50.000 e dizia "Configuração salva"; `CommitRequest.rows` seguia recusando
  acima de `IMPORT_MAX_ROWS` (5.000) com um erro sobre comprimento de lista. O
  teto da chave passou a ser o do processo — pela tela só se aperta.
- **Os horários da área administrativa apareciam três horas adiantados.** O
  backend serializa instantes sem fuso (a coluna é `timestamp without time
  zone`) e o `new Date()` cru os lia como hora local — a validade de um convite
  podia mostrar o dia seguinte. Passou a usar `parseApiDate`, que é o helper que
  o resto do aplicativo já usava.
- **Quatro chaves da cascata não chegavam ao container.** `REGISTRATION_MODE`,
  `ATTACHMENT_QUOTA_BYTES`, `UPLOAD_MAX_BYTES` e `IMPORT_MAX_ROWS` não estavam no
  `docker-compose.yml` — o mesmo defeito do `SMTP_TLS` corrigido na onda
  anterior, e no deploy a cascata `banco → .env → embutido` era `banco →
  embutido`. `tests/test_compose_env.py` agora reprova a ausência e a divergência
  entre o padrão do compose e o do `config.py`.
- **"Copiar link" mentia num deploy sem HTTPS.** `navigator.clipboard` não existe
  fora de contexto seguro — que é o "Cenário B" documentado no SETUP.md —, e o
  botão dizia "Link copiado" sem copiar nada (num dos casos estourando um
  `TypeError`). O novo `lib/clipboard.ts` recua para `execCommand` e devolve se
  copiou; a mensagem passou a depender do resultado.
- **Ninguém mais se desativa pela tela.** `delete_user` já barrava a
  auto-remoção; o `PATCH` não barrava a auto-desativação, que tem o mesmo efeito
  e é mais fácil de fazer sem querer — a sessão cai junto e o login seguinte é
  recusado. Rebaixar-se continua permitido.
- **A gravação de configuração tinha uma corrida de cache.** `set_value`
  invalidava antes do commit; nessa janela uma leitura concorrente cacheava o
  valor antigo *para sempre*. Passou a invalidar de novo depois do commit.
- **Administrador comum não tinha como promover ninguém.** O servidor aceitava
  `user → admin` vindo de um admin; a tela só oferecia o seletor a
  superadministradores. Agora oferece, sem a opção de criar superadmin.

### A auditoria da Onda 9: o que se corrige em banco vazio não se corrige

Uma segunda auditoria externa sobre a Onda 9 aprovou a separação Global × Workspace, as
permissões e o multimoeda manual, e reprovou a publicação com 2 achados críticos, 2 altos e
2 médios. Todos os seis procediam. **Dois eram piores do que o relatado** e um não reproduziu.

O fio comum dos dois críticos: *o caminho de criação foi corrigido e o de edição não*.

- **A migração de datas civis quebrava em qualquer banco com dados.** Ela lia as linhas com
  `sa.text()` sem tipo declarado, e sem tipo o SQLAlchemy não aplica processador de
  resultado: o driver do SQLite devolve a coluna `DATETIME` como `str`, e o `.time()`
  seguinte estourava `AttributeError`. Como o Dockerfile roda `alembic upgrade head` antes do
  uvicorn, isso é o container não subir. Passava no CI porque o CI migra um banco **vazio** —
  não havia linha para ler.
- **E, onde não quebrava, convertia pela metade.** A barreira contra colisão era um conjunto
  de instantes global por chamada, sem olhar a que recorrência a linha pertencia: a primeira
  despesa do dia 1º reancorava e ocupava o meio-dia, e toda outra linha daquele mesmo dia —
  de outras recorrências, sem relação nenhuma — era pulada e ficava com o bug que a migração
  existe para corrigir. A auditoria descreveu o sintoma; a leitura dos modelos mostrou que a
  barreira era pior ainda: em `transaction` o índice único é
  `(recurring_expense_id, occurrence_date)`, que **não menciona** a coluna movida, e em
  `importrow` não há índice único nenhum. Nas duas ela só atrapalhava. A vaga real é
  `(recorrência, instante)`, e só `income` tem um índice que a envolva.
- **Editar uma recorrência deixava a fatura no valor antigo.** `_create_instance` chamava
  `apply_statement_leg`; `sync_unpaid_instances` — o caminho que roda ao editar o template —
  atualizava valor, moeda, cartão e `statement_id` e parava aí. Uma assinatura de R$ 100 num
  cartão USD virava R$ 200 no lançamento e continuava cobrando US$ 20,70 na fatura, com o
  limite disponível preso ao número velho. Trocar o cartão era pior: a instância migrava para
  a fatura nova carregando a perna monetária da antiga e caía fora do total dela.
- **O backfill histórico cobrava IOF de quem não converteu nada.** Ele reimplementava
  taxa × (1 + IOF) por conta própria, e errava justamente o caso mais comum do seu recorte:
  US$ 20 num cartão USD (cuja perna contábil está em BRL só porque o workspace é BRL) viravam
  US$ 20,70. A regra correta já existia em `compute_statement_conversion`; o script passou a
  reusá-la. E ele só tocava a transação: fatura fechada usa o `total_amount` **congelado**,
  então o backfill apagava o aviso de linha incompatível e mantinha o total errado — pior que
  antes, porque agora invisível. Agora há uma segunda passada que recongela o total, e as
  faturas que passam a estar sub-pagas saem em destaque (status e pagamentos não são tocados:
  cobrar a diferença é decisão humana).
- **O Playwright não devolvia o terminal** — de novo, e a correção anterior tinha trocado
  `npm run dev` por `npx vite` acreditando ter resolvido o problema do processo neto (`npx`
  também é um wrapper Node). A causa real era outra: o atalho `reporter: 'html'` mantém o
  default `open: 'on-failure'`, e nesse modo o Playwright termina a rodada e **sobe um
  servidor HTTP** para exibir o relatório. O `playwright.shots.config.ts`, com o mesmo
  `webServer`, nunca travou — usa `reporter: 'line'`. Agora `open: 'never'`, o vite sobe por
  `node` direto, e a rodada devolve exit code 0 por conta própria.
- **O campo "Limite" mostrava R$ ao cadastrar um cartão em USD.** Uma variável paralela ao
  estado (`dialogCurrency`) caía na moeda de relatório durante a criação, ignorando o seletor.
  O cartão nascia correto, e era isso que tornava o erro traiçoeiro: a tela mostrava um número
  numa moeda e gravava noutra, sem sinal de que tinham divergido.

Os baixos, todos corrigidos: `?workspace_id=1.5` passava pela validação (`Number.isFinite`
aceita fracionário) e virava 422; `?page=1.5` virava `offset=150`; a listagem de faturas
fazia duas contagens **por fatura** dentro do laço (~120 consultas num cartão com 60 meses,
agora dois `GROUP BY`); o `CurrencyCombobox` não aceitava `id`, então os `<Label htmlFor>` de
"Moeda do cartão" e "Moeda do contrato" não chegavam à árvore de acessibilidade; e o engine
de teste nunca era fechado, deixando um `ResourceWarning` depois de uma suíte verde.

De quebra, um defeito que a auditoria não pegou: o comentário de `_create_instance` afirmava
usar `allow_fetch=False` no caminho de leitura, mas `apply_statement_leg` não aceitava esse
parâmetro — a materialização preguiçosa, que roda a partir de **rotas de leitura**, podia ir à
rede uma vez por ocorrência. O mesmo parâmetro que o backfill precisava fecha os dois.

**Um achado não reproduziu.** O relatório dava o CI como vermelho por `requirements.lock`
desatualizado, listando quatro transitivas a subir. Rodando o passo exato do workflow —
`pip-compile` **em cima do lock versionado** — em `python:3.12-slim` e em `ubuntu:24.04` com
Python 3.12, a saída é idêntica ao arquivo commitado nos dois ambientes. A divergência aparece
quando se compila para um arquivo de saída **novo**: sem o lock presente, o pip-tools perde as
preferências de versão e reresolve tudo para o mais recente do PyPI. O gate está verde — mas o
episódio expôs uma fragilidade real, e o `pip-tools` do CI, que era instalado sem versão,
passou a sair fixado do `requirements-dev.txt`.

**O gate que faltava:** `tests/test_migration_c7e3b81f04a9.py` migra um banco **povoado** — em
SQLite e em Postgres — e cobre os dois defeitos e os casos que não devem ser tocados. É o
irmão de `test_migration_a4e8c1b90f52.py`, criado pela mesma razão na auditoria anterior:
migração só testada em banco vazio não está testada.

### A moeda da fatura e a data que não tinha dono (ADR 0024 e 0025)

Uma auditoria externa sobre a onda anterior levantou 12 achados. Todos procediam. Os quatro
graves tinham duas causas, e as duas eram a mesma espécie de omissão: **ninguém tinha
decidido**, e cada caminho decidiu sozinho.

- **Ninguém decidiu em que moeda a fatura é denominada.** O ADR 0021 tornou o cartão pessoal
  (moeda = a de relatório do dono); o ADR 0015 grava todo lançamento na moeda-base do
  *workspace*. Dois ADRs certos, tomados em ondas diferentes, e nada ligando as duas moedas.
  Com cartão em USD e workspace em BRL, a fatura somava **US$ 0,00** com a compra listada
  logo acima: o filtro `currency == card.currency` não casava com linha nenhuma. O limite
  nunca era consumido, fechar a fatura **congelava o zero** como histórico, e o overview
  descartava a fatura em silêncio. A listagem, que não filtrava moeda nem status, exibia
  R$ 100 como `−US$ 100,00`. Três populações diferentes na mesma tela. Agora o lançamento tem
  duas pernas — a contábil e a de fatura —, e listagem, total, limite, fechamento e pagamento
  operam sobre o mesmo predicado.
- **Ninguém decidiu como escrever uma data civil.** A Onda 7 ensinou o backend a *ler*
  instantes no fuso do usuário e deixou a escrita implícita; todo produtor escolheu meia-noite
  por omissão. `2026-08-01 00:00Z` é 31 de julho em São Paulo, então a recorrência do dia 1º
  saía do próprio mês: `/me/income?month=2026-08` vinha vazio, `/me/overview` mostrava renda
  zero e o caixa não registrava nada — enquanto o `billing_month` da mesma linha dizia agosto.
  O frontend já ancorava tudo ao meio-dia (`T12:00:00`); o backend tinha zero ocorrências
  disso e seis de meia-noite. `civil_instant` é o par que faltava de `local_day`.
- **A troca da moeda-base cotava pelo dia em UTC.** Uma despesa das 22h de 31/07 buscava a
  taxa de 1º de agosto — e o valor errado ficava gravado, porque a reconversão reescreve o
  histórico. O dry-run errava junto, pedindo ao operador a cotação de um dia que não era o da
  despesa.
- **`cryptography 49.0.0` reprovava o `pip-audit --strict`** (PYSEC-2026-3552) e bloqueava
  qualquer release. Entra pelo extra `[crypto]` do PyJWT, que não tinha piso próprio.

Os outros oito, todos corrigidos: o extrato mascarava erro de API como "mês vazio" (os cinco
hooks de `/me` descartavam `isError`, e os totais caíam no `?? 0` — um mês zerado é uma
afirmação financeira, e era falsa); `?workspace_id=abc` virava `NaN` na URL; `?page=999` era
um beco sem saída; o token `--warning` do tema reprovava o contraste WCAG **em toda parte**
onde servia de texto, não só no aviso de cotação; a frase daquele aviso estava invertida
("somem de novo quando houver cotação" — é o contrário); cartão e financiamento não deixavam
escolher a moeda pela UI; a linha do drill-down tinha 53px clicáveis de 475px e o nome
acessível do link omitia o valor; a confirmação de reabrir fatura descrevia o caixa ao
contrário; a exceção do `npm audit` sobreviveu à vulnerabilidade que a justificava; e o
Playwright não devolvia o terminal no Windows (o `npm run dev` deixava o vite como processo
neto, o mesmo defeito que o uvicorn já tinha resolvido).

Dois pontos da auditoria não procediam como descritos e estão registrados: `page` **já** era
NaN-safe (o defeito era outro, nos ids), e o `ExcludedForeignNotice` era o **melhor** dos
amber do repositório — corrigir só ele deixaria os outros dez piores intactos.

### Saldo de fatura, arquivamento e data efetiva de verdade (ADR 0023)

Uma auditoria externa sobre a onda anterior aprovou a separação Global × Workspace e não
achou regressão, mas encontrou um P0 e cinco P1 na camada financeira. Três deles tinham a
mesma causa: **um número agregado nascia de uma consulta própria**, com o seu filtro e a
sua data, em vez de sair das linhas que ele resume.

- **Fatura podia ser encerrada pagando R$ 1.** Qualquer valor positivo marcava a fatura
  como paga, liberava o limite inteiro do cartão e ainda impedia completar o pagamento — a
  fatura já não estava `closed`. Nada somava `StatementPayment.amount`, embora o schema
  sempre tenha admitido N pagamentos por fatura. Agora o saldo é cumulativo, o limite
  comprometido é o SALDO (pagar metade libera metade), sobrepagamento é recusado citando o
  saldo (a regra do ADR 0009), e a fatura só vira `paid` no zero.
- **Excluir cartão ou financiamento apagava o passado.** As consultas de caixa filtravam
  `deleted_at`, então arquivar o cadastro reescrevia meses fechados. O filtro saiu: o fato é
  o pagamento, o cadastro é rótulo. Financiamento ativo com parcelas em aberto passou a
  exigir confirmação explícita para ser arquivado.
- **A parcela de financiamento ia para o mês do vencimento, na moeda crua.** Pagar
  adiantado zerava o caixa do mês em que o dinheiro saiu; e uma parcela em USD num workspace
  BRL virava uma despesa que nenhuma agregação somava (todas filtram `currency == base`).
  Agora `paid_at` é informável, é dele que sai a data da despesa, e a conversão passa pelo
  mesmo pipeline dos lançamentos comuns (sem IOF — parcela não é compra no cartão).
- **Cancelar a despesa vinculada fazia a saída sumir dos dois lados.** A dedup só perguntava
  "existe uma transação?", sem olhar o status. Agora exige que ela CONTE; e os campos que
  definem a identidade financeira do vínculo ficaram imutáveis.
- **O caixa convertia tudo pela cotação do dia 1º do mês.** USD 100 pagos no dia 25 com o
  dólar a 6 entravam como se fossem 5. `CashFlowService` virou uma lista de linhas — cada
  movimento com a sua data efetiva —, e os totais e os dois `breakdown` passaram a sair
  dessas mesmas linhas.
- **O aplicativo tinha duas noções de "hoje".** `datetime.now(UTC)` na fatura vencida e nos
  compromissos, `date.today()` na recorrência, na previsão e na data de cotação; em fuso
  negativo elas discordam entre 21h e a meia-noite. O fuso existia só como `TZ` no Compose,
  invisível para o `Settings` e ausente em qualquer uvicorn iniciado à mão. Agora há
  `APP_TIMEZONE` e `today_local()`/`month_bounds_utc()`: a janela do mês é o calendário
  LOCAL convertido para UTC, e uma renda recebida às 22h de 31 de julho em São Paulo
  pertence a julho.
- **`billing_month` derivado de UTC punha o lançamento no mês seguinte.** Quem chama a
  API sem `billing_month` — script, integração, o próprio e2e — tinha a despesa carimbada
  em agosto ao lançar às 22h de 31 de julho, e ela não aparecia em tela nenhuma (todas
  pedem julho). O formulário sempre mandou o campo e mascarava o defeito. As rotas passam
  a converter com `month_key_local`, porque sabem que receberam um instante ISO; o import
  de CSV e o listener de mapper **não** convertem, porque ali `transaction_date` é (ou
  pode ser) um dia de calendário à meia-noite, e converter jogaria "01/03" para fevereiro.
  Era esta a causa da falha do `e2e-prod/realtime_invite`: o evento de WebSocket chegava e
  a invalidação rodava; o lançamento é que estava no mês errado.

**Extrato global** (`/me/ledger`): o refactor do caixa entregou-o de graça — é a mesma lista
de linhas, filtrada por origem, workspace, cartão ou contraparte. Os blocos de caixa da
Visão global levam a ele já filtrados, então o detalhe fecha com o total por construção. Os
relatórios pessoais ganharam seletor de 3/6/12 meses (a API já aceitava 1..12).

**O gate de `npm audit` podia ficar verde sem ter auditado nada.** Quando o registry falha,
o npm imprime um JSON de erro em stdout com código != 0; ele passava pelo `catch`, não tinha
a chave `vulnerabilities`, e o `?? {}` transformava isso em "nenhuma vulnerabilidade". Agora
o gate valida a forma do relatório, cruza com `metadata.vulnerabilities` e falha fechado.

**Inputs que não cabiam o valor digitado.** Dentro do diálogo de Nova Despesa num telefone
de 360px, o campo "Valor Total" tinha 48px — dos quais 36 eram o padding do prefixo "R$" —
porque o seletor de moeda ocupava 92px fixos numa coluna de `grid-cols-2` sem prefixo
responsivo. Os grids dos formulários passaram a quebrar abaixo de `sm`, as larguras fixas
viraram elásticas, nasceu um `Textarea` (as descrições eram campo de uma linha) e a sintaxe
Tailwind v4 que não compila em v3 — e por isso não emitia CSS nenhum — foi convertida.

**Acessibilidade.** A linha de membros transbordava o cartão em 393px (328px de controles
que se recusavam a encolher); as ações de editar/excluir eram invisíveis no toque em cinco
telas; o cartão de crédito tinha `<span role="button">` dentro de `<button>`, sem ativação
por teclado; e a gaveta "Mais" era um `role="dialog"` sem nome acessível, focus trap, Escape
ou trava de rolagem — agora usa o `Dialog` do projeto, que já era um bottom sheet no mobile.

### Recurso financeiro é da pessoa e não mora em workspace nenhum (ADR 0021)

Uma auditoria externa encontrou um vazamento de privacidade em cartão de crédito, e a causa
não era um endpoint distraído: era o modelo. A Onda 2 tinha deixado o cartão morar num
workspace e criado uma tabela de vínculo com dois níveis — `use` (lançar e ver o próprio
subtotal) e `full` (fatura inteira). O predicado que implementava a distinção,
`card_full_access_here()`, **existia sem um único chamador**. Na prática, todo cartão
compartilhado entregava a quem tivesse `full_workspace` no workspace de destino o limite, o
valor comprometido e a fatura inteira — com as compras privadas feitas em outro workspace
dentro dela. `GET .../statements/{id}` piorava: filtrava as transações só por
`statement_id`, sem workspace e sem envolvimento. E `close`, `pay` e `reopen` pediam apenas
`require_role(member)`, então qualquer membro que enxergasse o cartão controlava o ciclo da
fatura do dono.

E, ao mesmo tempo, **não servia**: usar o cartão compartilhado no destino respondia `400`,
porque a criação de lançamento exigia `card.workspace_id == workspace_id`. Vazava e não
funcionava.

Por decisão do dono, cartão, conta de pagamento, financiamento e renda passam a ser da
PESSOA, sem `workspace_id`:

- as cinco tabelas de vínculo recurso↔workspace foram removidas, as colunas `workspace_id`
  saíram de `creditcard`/`paymentaccount`/`financing`/`income`/`recurringincome`, e o dono
  virou NOT NULL (migração `a4e8c1b90f52`, com backfill a partir do workspace de origem);
- as rotas foram para `/me/...`, com a sessão no gate;
- `personal_scope` substitui `owner_scope` nesses domínios e **não consulta
  `financial_access`** — acesso completo governa dado do workspace, nunca recurso pessoal.
  Trocar o modelo sem trocar o predicado teria reaberto o vazamento com o schema novo;
- o gate de uso virou a propriedade: lançar exige que o cartão seja de quem lança, e a conta
  informada por um pagador tem de pertencer **àquele pagador** — `_validate_payer_accounts`
  nunca olhava `payer.user_id`, então bastava conhecer o id para declarar que a despesa saiu
  da conta bancária de outra pessoa do mesmo workspace.

### O "Resultado do mês" que mentia

O Painel mostrava `my_net = my_income − my_expenses` com a renda **global** e a despesa
recortada **naquele workspace**. Com salário de 9.000 e 1.150 de despesa na Casa, ele
anunciava 7.850 de sobra — ignorando os 500 gastos noutro workspace. Num terceiro workspace
o mesmo salário seria combinado com outro subconjunto de despesas e daria uma terceira
"sobra", todas maiores que a real.

Renda e resultado saíram do resumo, do histórico e da previsão do workspace; existem num
lugar só, `/me/overview`, onde o denominador é o consumo somado de todos. O Painel ganhou
`paid_by_me` e `my_balance`, que respondem "paguei 1.300, consumi 1.150, tenho 150 a
receber". A renda "da casa" também saiu: sem modelo de beneficiários ela era creditada 100%
a quem cadastrou — o aluguel recebido pelo casal aparecia todo para um só.

### Permissão financeira, enfim, na tela

`financial_access` existia no backend e em lugar nenhum do frontend: a permissão era
concedível apenas por chamada direta à API. Agora há um seletor "Só o que o envolve / Todo o
workspace" na linha de cada membro e nos dois formulários de convite.

### Outros

- **Compromissos separados por prazo.** O "Total a pagar" somava a próxima fatura com o
  principal inteiro dos financiamentos — juntava o que vence em cinco dias com o que vence
  em quinze anos. `/me/commitments` devolve vencido, a vencer no mês, próximas parcelas,
  saldo devedor e comprometimento mensal.
- **Moeda do que é pessoal** passa a ser `User.report_currency`. Herdava a moeda-base do
  workspace ABERTO, então a mesma renda nascia em moedas diferentes conforme a tela por onde
  foi criada. E trocar a moeda-base de um workspace deixou de reescrever renda/conta/cartão
  dos membros — num usuário de dois workspaces, o segundo desfazia o primeiro.
- **Corrida do cadastro/login.** `ProtectedRoute` lia um espelho em Zustand que só é
  atualizado quando o refetch de `auth-me` resolve; entre o `invalidateQueries` e a
  resposta, o estado era indistinguível de "sessão morta" e o guard mandava para `/login` no
  meio de um cadastro bem-sucedido.
- **307 e o cookie.** Rotas de coleção em `/me` respondem com e sem barra final: o
  redirecionamento automático do Starlette descarta o cookie de sessão, e `/me/income/`
  devolvia 401 enquanto `/me/income` devolvia 200.
- **Navegação:** um item ativo por vez (o teste de prefixo acendia Painel e Relatórios
  juntos), "Rendas" saiu da seção "Compartilhado" (é o dado mais privado do sistema), e há
  um único item "Compromissos". `h1` em Cartões, Financiamentos, Importar e Configurações.
- **`npm run lint` inteiro volta a passar** — varria `.pytest_cache` e morria com `EPERM`.
- **Compartilhamento entre PESSOAS** (o casal que divide tudo mas tem contas separadas) fica
  desenhado em `docs/estudo-recursos-compartilhados.md`, não implementado: o modelo anterior
  errava a forma ao vincular recurso a espaço em vez de a co-proprietários.


### Renda é da pessoa, não do workspace (ADR 0019)

- **"A renda não está global — criei um novo workspace e não contou."** Todo o domínio
  nascia com `workspace_id NOT NULL`, então **salário pertencia a um espaço de
  colaboração**, o que é falso: renda é de quem recebe. Duas causas somadas: a coluna
  obrigatória, e o `my_income` do `ReportService` filtrando por
  `Income.workspace_id == workspace_id` — mesmo existindo o dado, o recorte pessoal o
  escondia. Quem participa de duas casas cadastrava o mesmo salário duas vezes, e as
  cópias divergiam na primeira correção.
- Pior no caminho recorrente, que é o que se usa de verdade: a materialização preguiçosa
  era escopada por workspace e o curto-circuito `_tem_template_ativo` devolvia `False`
  num workspace recém-criado (ele não tem template nenhum), então o salário global nunca
  era gerado ali. `generate_due_income` e `ensure_and_commit` passaram a receber
  `user_id`, e as quatro rotas de leitura que materializam o repassam.
- **`workspace_id` anulável** em `Income`/`RecurringIncome`: `NULL` = pessoal (global),
  preenchido = renda **da casa** (aluguel de imóvel compartilhado). Criar renda nasce
  pessoal, porque é a verdade do caso comum.
- **Global para MIM ≠ público para a casa.** Cinco tabelas de vínculo
  (`IncomeWorkspaceShare`, `RecurringIncomeWorkspaceShare`, `CardWorkspaceAccess`,
  `PaymentAccountWorkspaceShare`, `FinancingWorkspaceShare`) dizem a quais orçamentos o
  recurso CONTRIBUI; vazio é privado. Sem isso, tornar a renda global viraria "meu salário
  entra no orçamento de toda casa de que participo" — o vazamento do ADR 0018 reaberto
  por outra porta. A ocorrência materializada herda os compartilhamentos do template,
  senão compartilhar um salário valeria só no mês do gesto.
- **Cartão compartilhado deixa de ser cadastro duplicado.** Usar o mesmo cartão em dois
  workspaces exigia dois cadastros, **cada um gerando a sua fatura** — a mesma dívida
  contada duas vezes no Endividamento e na Previsão. `CardWorkspaceAccess.access` separa
  *usar* de *devassar*: com `use`, o workspace lança compras e vê o subtotal dele; limite
  e fatura inteira continuam do dono (a granularidade que faltava na onda anterior).
- **`User.report_currency`**: o que é pessoal não tem workspace de onde herdar a
  moeda-base, e converter pela base de quem por acaso disparou a leitura faria o MESMO
  salário valer números diferentes conforme a tela aberta.
- **Admin não manda em renda pessoal alheia** — ele administra a casa, não o salário de
  quem mora nela. Renda da casa continua sob a alçada dele.
- Migração `e1c9b482f57a` converte as rendas existentes em pessoais **compartilhadas com o
  workspace de origem**, nessa ordem (é do `workspace_id` que sai o destino; invertida, a
  informação se perderia). O dono passa a ver a própria renda em todos os workspaces e
  nenhum total de casa muda. Deixar como estava faria a correção não valer para os dados
  que já existem — os de quem reclamou.

### Início global e pessoal; workspace na URL (ADR 0020)

- **O Início era a dashboard de um workspace disfarçada de tela pessoal**: lia o
  `currentWorkspaceId` do `localStorage` e misturava "minha parte" com "Últimos
  lançamentos" da casa inteira. Agora `/overview` soma TODOS os workspaces da pessoa.
- **Quatro números, nomeados pelo que são.** O app chamava tudo de "gasto":
  **consumo** (minha parte), **saída de caixa** (o que saiu do meu bolso — *não existia
  em lugar nenhum do sistema*), **a pagar/receber** (a diferença, por casa) e
  **resultado do mês** (renda − consumo). O resultado desconta consumo, não caixa:
  adiantar dinheiro por outro é crédito a receber, e descontando o caixa quem paga a conta
  do restaurante apareceria no vermelho todo mês.
- **Saldos não se compensam entre workspaces**: dever 100 na casa e ter 100 a receber na
  viagem não é estar quitado — são pessoas e acordos diferentes.
- **Workspace na URL** (`/w/:workspaceId/...`). Fora dela, o mesmo `/income` significava
  coisas diferentes conforme um estado invisível: link compartilhado abria na casa de quem
  clicou, duas abas disputavam a MESMA chave (e a despesa ia para a casa errada), e o
  botão "voltar" não voltava. Um `WorkspaceGuard` confere a associação antes de a tela
  montar — fecha o caso de quem foi removido e seguia com o app apontado para lá, num
  ciclo de 403 sem explicação.
- O refactor coube em **uma linha por hook**: `useWorkspaceId()` lê `useParams()` e os 22
  hooks de dados trocaram `useUIStore()` por ele, com as query keys, os guards `enabled` e
  o contrato de `lib/ws-events.ts` idênticos.
- Renomeações: "Seu saldo" → **"Resultado do mês"** (era resultado do período, não saldo
  bancário); "Dívidas" → **"Acertos entre pessoas"**; "Endividamento" → **"Compromissos
  financeiros"** (dois eixos com nomes quase iguais).

### Corrigido — as animações do app não existiam

- **`tw-animate-css@1.4` é escrito inteiramente em sintaxe Tailwind v4** (`@utility`,
  `@theme inline`) e o projeto é TW 3.4: as at-rules não viravam CSS nenhum. Não eram
  "avisos de build" — **todas as animações estavam mortas em silêncio**. Trocado pelo
  plugin nativo `tailwindcss-animate`.
- E a correção revelou duas coisas que o silêncio escondia:
  - **`--income` reprovava no contraste WCAG AA.** 4,35:1 sobre `--background` e 3,74:1
    sobre `--expense-subtle`, contra os 4,5:1 exigidos. Passava porque os valores de
    dinheiro eram `font-black`, e o axe aplica o limiar frouxo de 3:1 a negrito grande —
    ao alinhar a tipografia ao design system (24 `font-black` → `font-semibold`, item que
    o roadmap já dava como concluído), o limiar real apareceu. Tokens escurecidos para
    L=0,47: ≥5,1:1 em toda superfície.
  - **A auditoria de a11y media durante o `fade-in`**, com o elemento semitransparente.
    `e2e/a11y.spec.ts` passou a esperar `document.getAnimations()` assentar.
- `docker-compose.yml`: healthcheck do frontend usava `localhost`, e o nginx da imagem
  escuta `listen 80` sem `listen [::]:80` — com IPv6 no container, `localhost` resolve
  para `::1` e o serviço saudável aparecia como `unhealthy`. Agora `127.0.0.1`.
- React Router: **não existe versão corrigida** para GHSA-qwww-vcr4-c8h2 (a faixa afetada
  é 7.12.0–8.2.0 e a última publicada é 7.18.2; o "fix" do npm é o downgrade quebrado para
  7.11.0). O aviso é sobre o modo RSC — verificado que o app usa só `BrowserRouter`
  declarativo, sem `createBrowserRouter`, loaders, actions ou APIs `unstable_*`. Subimos
  para a última (7.18.2) e documentamos; downgrade não se justifica.
- `docs/frontend-redesign/08-roadmap-e-tasks.md` afirmava que a auditoria de acessibilidade
  "nunca foi executada" (o `a11y.spec.ts` roda no gate desde a onda anterior) e dava
  F1.3 como concluída com 24 `font-black` vivos. Os dois corrigidos.

### Segurança — membro do workspace lia o que não era dele (ADR 0018)

- **`app/api/deps.py` tinha 39 linhas e duas funções, e era toda a autorização do sistema.**
  `get_workspace_membership` é satisfeito por qualquer papel — inclusive `viewer` — e era o
  gate de praticamente todo `GET`; `require_role` protegia só as mutações. O papel controlava
  a escrita e **não protegia a leitura**: cada listagem filtrava `workspace_id + deleted_at`
  e mais nada. Quem entrava no workspace por convite lia o **salário** dos outros membros, os
  **lançamentos individuais** de quem não o envolveu, os **anexos** desses lançamentos (o
  arquivo, bastando o id), os **cartões** alheios com nome do banco e limite, e os **totais da
  casa** com a quebra de dívida por pessoa. Não foi descuido pontual: eram ~15 rotas escritas
  em momentos diferentes, cada uma copiando o filtro da vizinha.
- **Papel e visibilidade agora são eixos separados.** `WorkspaceMembership.financial_access`
  (`involved_only` | `full_workspace`) diz o que a pessoa VÊ; `WorkspaceRole` continua dizendo
  o que ela FAZ. `admin` e `owner` têm acesso completo pelo cargo. A regra toda vive em
  `app/domain/access_policy.py`, irmão do `query_policy.py` — não havia camada de acesso para
  estender, porque `query_policy` é política de status e moeda.
- **"Envolvido" é predicado SQL** (`involvement_filter`): criou, pagou, tem divisão direta ou
  participa da divisão de um item. `or_` de subqueries e nunca `join` — join multiplicaria a
  linha, e a contagem e a soma da listagem derivam da mesma statement, então herdam o recorte
  de graça. Antes, "2 lançamentos, R$ 500 de saídas" apareceria acima de uma lista com 1 item.
- **Invisível responde 404, não 403.** 403 confirmaria que o registro existe naquele id, e a
  existência já é informação. (`viewer` leva 403 do `require_role` antes do corpo da rota —
  "você não escreve nada aqui" não revela nada sobre o registro.)
- **Número da casa suprimido vira `null`, nunca `0`.** Zero é mentira somável: o membro
  juntaria "a casa gastou 0" com "eu gastei 300". Vale para `total_expenses`, `total_income`,
  `net_savings`, `categories`, as barras dos 6 meses e a previsão inteira — que é projeção de
  caixa da casa, e por isso sobra só `my_budget`. No frontend o `?? 0` do Início renderizaria
  **"Casa R$ 0,00"** ao lado da despesa real da pessoa; agora `null` continua `null`.
- **O ledger de dívidas é calculado inteiro e recortado na saída.** O pareamento guloso de
  `_settle_balances` precisa de todos os saldos: filtrar antes daria outro emparelhamento e um
  valor devido **diferente do real**. Quando há recorte, `totals` passa a ser o total do que
  está listado.
- **As quatro formas divergentes de trava de autoria viraram uma** (`assert_can_write`), e o
  furo do `None` fechou. Em seis lugares a condição era
  `created_by_user_id not in (None, membership.user_id)`, o que fazia de todo registro sem
  autoria um registro de todo mundo. Onde o `None` significa "recurso da casa" (cartão, conta
  de pagamento, template recorrente) isso agora é o parâmetro explícito `null_is_shared`.
- **`CreditCard` ganhou `owner_user_id`** — era a única entidade financeira sem coluna de
  usuário, logo sem trava nenhuma: qualquer member mudava o limite do cartão de outro. A
  migração atribui o dono só onde o workspace tem um único membro; com vários, fica
  "compartilhado legado" (adivinhar esconderia da pessoa o cartão que ela usa todo dia).
- **Convites nascem fechados.** `financial_access` viaja no convite (quem convida decide, não
  o convidado) com default `involved_only`; `max_uses` do convite por link passa de `None`
  (ilimitado por 7 dias) para **1**; e o convite por e-mail passou a honrar `expires_days`, que
  era ignorado em favor de 7 dias fixos no braço.
- `member.updated` entrou nos eventos de **resync completo** (`lib/ws-events.ts`): rebaixar o
  acesso de alguém tem de esvaziar a tela dele na hora, não no próximo F5.
- `canWrite` de `TransactionItem`/`TransactionDetailDialog` era `true` por default, então todo
  ledger renderizado sem a prop mostrava editar/excluir habilitados a um viewer — era o caso do
  Início. Agora é **fail-closed**.
- Testes: `tests/security/test_privacy_matrix.py` cobre
  `papel × acesso × envolvido/não-envolvido` em todas as leituras (o `test_idor_scan.py` cobria
  isolamento *entre* workspaces e nada de privacidade *dentro* de um), e
  `test_read_policy_coverage.py` percorre o router e falha quando aparece um `GET` novo sem
  política — com dispensas explícitas e justificadas, para ignorar ser decisão e não
  esquecimento.

### Corrigido — o cron de câmbio morria na primeira query

- **`scripts/backfill_rates.py` estourava `InvalidRequestError: expression 'RecurringExpense'
  failed to locate a name` no container `cron`** — ou seja, o store de câmbio nunca era
  alimentado pelo agendador, e cada conversão dependia da busca preguiçosa na fonte externa.
  A mensagem culpa a recorrência, mas o script não toca em recorrência: os `Relationship` do
  SQLModel referenciam as classes por **nome (string)**, e o SQLAlchemy resolve esses nomes
  configurando **todos** os mappers do registry na primeira query — não só o da tabela
  consultada. O script importava o `ExchangeRate` e, por tabela, o `Transaction` (via
  `app.domain.query_policy`), mas nada importava o `RecurringExpense`; o `select(ExchangeRate)`
  então tentava resolver `Transaction.recurring_expense` contra um registry incompleto.
- A lista de models virou **uma só**, em `app/models/__init__.py`: importar qualquer model
  registra todos. Antes ela existia copiada em quatro lugares (`app/main.py`, `alembic/env.py`,
  `tests/conftest.py` e o script de migração de anexos) — e os entrypoints que não tinham cópia,
  como os dois scripts de cron, ficavam com o registry pela metade. `tests/test_model_registry.py`
  fecha a porta: um teste falha se um model novo ficar fora da lista, e outro sobe um processo
  limpo (como o cron) e exige que os mappers configurem.

### Corrigido — tempo real na troca de workspace (item aberto da 4ª rodada)

- **Trocar de workspace pelo switcher deixava o tempo real mudo até um F5.** O relato era
  "o socket novo recebe o `hello` e nenhum evento depois", e o diagnóstico apontava o
  *rewire* do socket. Não era isso: o socket reconecta certo. O defeito estava na **janela
  do handshake**, e em duas pontas ao mesmo tempo.
  - No servidor, a ordem era: ler o `event_seq` → mandar o `hello` → **entrar na sala**.
    Toda mutação commitada nessa janela era publicada para uma sala que ainda não continha
    o socket — evento perdido.
  - No cliente, o `hello.seq` era adotado como marco **sem qualquer garantia de que o cache
    correspondia a ele**. O cache é preenchido por HTTP: uma mutação commitada entre o `GET`
    e a entrada na sala já vem contada no `hello.seq` sem estar nos dados. E aí nada
    conserta — o evento seguinte chega **em ordem**, então não há lacuna de `seq` para
    detectar, e o lançamento do outro membro fica invisível para sempre.

  Trocar de workspace batia nisso quase sempre porque o switcher refaz todas as queries no
  clique enquanto o handshake ainda leva centenas de ms. A mesma janela existia (mais
  estreita) na carga da página. Agora o socket entra na sala **antes** de o `seq` do `hello`
  ser lido, e o **primeiro `hello`** de um workspace força resync total; o `hello` nunca
  regride o marco, porque nessa ordem um evento pode chegar antes dele.

  Gates: `test_evento_na_janela_do_handshake_nao_e_perdido` (backend), quatro casos novos em
  `use-workspace-events.test.tsx` e o e2e `realtime_switch.spec.ts`, que amplia a janela de
  propósito (`routeWebSocket`) em vez de depender de timing. O `reload()` que existia no
  meio de `realtime.spec.ts` era maquiagem do sintoma e saiu.

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
