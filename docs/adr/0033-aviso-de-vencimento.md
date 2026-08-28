# O aviso de vencimento, e o teclado de permissão que não se pede duas vezes

Status: aceito, 2026-08-28. Relacionados: 0011 (ciclo da fatura), 0018 e 0021
(privacidade e recurso pessoal), 0022 (caixa efetivo), 0029 (competência ×
caixa), 0025 (`civil_instant`).

## Contexto

O app sabe o que a pessoa deve e quando — e não conta para ela. A tela de Contas
a pagar e a de Compromissos existem, mas são **puxadas**: só informam quem abre.
Uma conta esquecida é a falha mais cara que este app pode deixar acontecer, e é
justamente a que ele tem todos os dados para evitar.

O pedido do dono foi literal: *"notificações de contas a pagar; conforme for
chegando mais próximo, chegar notificações"*.

## O que existe, e por isso não será construído de novo

- **Um serviço `cron` no `docker-compose`**, com laço horário e um ramo diário
  (câmbio de hora em hora, expurgo a cada 24h). Ele já carrega `APP_TIMEZONE`,
  `DATABASE_URL` e o mesmo `Settings` do backend — e o comentário dele diz que
  "toma decisões de calendário e precisa enxergar o mesmo fuso". É a casa do job.
  **Não entra APScheduler nem Celery.**
- **`Notification` + `notification_service.notify()` + `NotificationCenter`** (o
  sino). Nasceram para convite, mas o modelo é genérico.
- **E-mail em produção** (`email_service`, templates, Resend com DNS pronto).
- **PWA instalável**: manifesto, ícones, `sw.js` à mão, `use-install-prompt`.
- **A regra de vencimento**: `payables_service._vencimento()` já é
  `local_day(transaction_date)`, e o atraso (`overdue_total`) já é calculado.

## Decisão

### 1. Três obrigações, não uma

Notificar só `payables` entregaria uma funcionalidade que parece completa e não
é: o `payables_service` **exclui compra no cartão de propósito** — "quem se paga
é a fatura, e ela já tem lugar próprio em Compromissos". A fatura do cartão é a
conta que mais dói esquecer, e ficaria calada.

O aviso cobre as três, cada uma com a data que ela realmente tem:

| Fonte | Vencimento | Observação |
|---|---|---|
| Conta a pagar | `local_day(transaction_date)` | é o que a tela já mostra |
| Fatura de cartão | `Statement.due_date` | data real, no banco |
| Parcela de financiamento | `FinancingInstallment.due_date` | data real, no banco |

A conta a pagar usa a data do lançamento porque é a única que ela tem — e é a
mesma que a tela de Contas a pagar já chama de vencimento. Documentado aqui para
que ninguém descubra sozinho depois: para um boleto lançado no dia em que chegou,
essa data é a da chegada, não a do vencimento. **Um `due_date` opcional no
lançamento resolveria, e fica de fora** (ver "O que fica de fora").

### 2. Três marcos, e nunca mais que três avisos por conta

"Conforme for chegando mais próximo" pede escala, não um aviso só. Mas cada aviso
a mais é fadiga, e fadiga transforma notificação em ruído que se desliga.

- **D-3** (configurável, 1..15): dá tempo de mover dinheiro.
- **No dia**: o lembrete que de fato importa.
- **D+1, uma única vez**: venceu e continua em aberto.

Três é o teto por conta e por pessoa. O que garante isso é a tabela do item 4.

### 3. O sino é o registro; o push é a entrega

São camadas diferentes, e confundi-las seria um erro de projeto:

- **Sino: sempre.** Não depende de permissão, de navegador, de iPhone nem de
  rede no momento certo. É o registro durável, e funciona para quem nunca ativar
  nada.
- **Push: se a pessoa ativou.** É o único canal que alcança com o app fechado.
- **E-mail: preferência, desligado por padrão.** Ninguém pediu e-mail; ligá-lo
  sozinho é spam. Fica à mão porque é o único canal que atravessa o iPhone sem
  instalação (ver item 7).

### 4. `AvisoDeVencimento`: a tabela que existe só para não repetir

O job roda todo dia. Sem estado, ele reavisaria a mesma conta todos os dias até
ela ser paga — que é exatamente como uma funcionalidade útil vira spam.

```
AvisoDeVencimento(user_id, fonte, fonte_id, marco, vencimento)
  UNIQUE (user_id, fonte, fonte_id, marco, vencimento)
```

O `vencimento` entra na chave **de propósito**: se a pessoa corrigir a data da
conta, o par muda e o aviso volta a valer. Uma conta que se moveu merece ser
avisada de novo — a chave sem a data trataria a correção como "já avisei".

Essa mesma restrição é o que torna seguro rodar o job mais de uma vez no mesmo
dia (item 5) e o que dispensa qualquer trava: no pior caso a segunda execução
esbarra na unicidade e não escreve nada.

### 5. Hora certa, sem mexer no laço que já existe

O ramo diário do `cron` roda "24h depois que o contêiner subiu" — ou seja, numa
hora que depende de quando houve o último deploy. Para expurgo isso é
indiferente; para notificação é inaceitável: "sua conta vence hoje" às 3 da manhã
acorda a pessoa e queima o canal.

O script roda **de hora em hora** e ele mesmo decide: se a hora local não é a
hora do aviso (`HORA_DO_AVISO`, padrão 9), sai na hora sem tocar no banco. A hora
é lida no `APP_TIMEZONE`, que o `cron` já recebe.

Isso mantém o laço do compose intacto, torna a hora determinística e
configurável, e sobrevive a restart — porque a unicidade do item 4 é quem
garante que rodar duas vezes não duplica.

### 6. Um push por marco, não um por conta

Cinco contas vencendo não são cinco notificações. O job apura o conjunto de
contas que **cruzaram** o marco naquela execução, grava uma linha de dedupe para
cada uma, e emite **um** aviso que as resume — no sino e no push. O toque abre a
tela da fonte predominante.

### 7. A matriz de plataforma, que decide a interface

O push é o padrão Web Push com VAPID; não há Firebase, nem app nativo.

| Onde | Chega? | Observação |
|---|---|---|
| Android — Chrome, aba comum | **Sim** | Chega com o Chrome fechado; atribuída ao Chrome |
| Android — app instalado (WebAPK) | **Sim** | Mesmo encanamento; ícone e nome do app |
| PC — Chrome/Edge | **Sim** | Central do Windows; exige o Chrome vivo (mesmo em segundo plano) |
| iPhone/iPad — Safari ou Chrome, aba | **Não** | A Apple não permite push em aba |
| iPhone/iPad — instalado na Tela de Início | **Sim** (iOS 16.4+) | Só via Safari → Compartilhar → Adicionar à Tela de Início |

**A consequência de interface é obrigatória**: para quem está num iPhone e ainda
não instalou, oferecer "Ativar notificações" é oferecer um botão que não pode
funcionar. Ali a tela pede a instalação primeiro. Isso não é polimento — é a
diferença entre a funcionalidade existir ou não naquele aparelho.

### 8. A permissão se pede UMA vez, e só depois de explicar

`Notification.requestPermission()` é irreversível na prática: negado, o navegador
não deixa perguntar de novo, e o conserto passa a ser um caminho nas
configurações do navegador que ninguém encontra sozinho. Disparar o prompt nativo
assim que a pessoa entra é a forma mais eficiente de perder o canal para sempre.

Por isso, em duas etapas:

1. **Convite nosso**, explicando o que ela ganha — não "permitir notificações",
   e sim "avisamos 3 dias antes e no dia do vencimento". Tem "Ativar" e
   "Agora não".
2. **O prompt do navegador só depois do clique em "Ativar"** — que é o gesto do
   usuário que a API exige, e a única situação em que a resposta tende a ser sim.

Quem disser "Agora não" **não some**: fica um botão discreto **ao lado do sino** e
**na tela de Contas a pagar**, que é onde a falta do aviso dói. O convite volta
sozinho depois de 7 dias; o botão fica sempre.

Quem já negou no navegador vê, no mesmo lugar, a instrução de como reverter — em
vez de um botão que não faz nada.

### 9. O que a notificação mostra, e o que ela cala

O payload do Web Push é criptografado ponta a ponta: o serviço do Google/Mozilla
transporta e **não consegue ler**. A exposição real não é a rede — é a **tela de
bloqueio**, onde qualquer um que olhe o aparelho lê o que chegou.

Num app cujos ADRs 0018 e 0021 tratam a vida financeira como privada, o padrão
não pode ser gritar quanto se deve. Então: **o valor não vai no aviso por
padrão** — vai o que vence e quando ("Aluguel vence amanhã"). Há uma preferência
para incluir o valor, para quem prefere.

### 10. Uma inscrição pertence ao último que entrou

`endpoint` é único. Se duas pessoas usam o mesmo navegador, a segunda a ativar
**toma** a inscrição da primeira — que é o comportamento correto: a primeira não
pode continuar recebendo as próprias contas num aparelho que agora é de outra.

Resposta `404`/`410` do serviço de push significa inscrição morta (app
desinstalado, permissão revogada): a linha é apagada na hora.

### 11. Sem chave VAPID, a funcionalidade se desliga sozinha

Ambiente de desenvolvimento não terá chave. Sem `VAPID_PUBLIC_KEY`, o endpoint de
configuração responde `enabled: false`, a interface não oferece nada, e o job não
tenta enviar push — o sino e o e-mail continuam funcionando. A chave pública
chega ao front por **endpoint**, não por variável de build, para que girá-la não
exija recompilar o frontend.

## Consequências

- Migração nova: `pushsubscription` e `avisodevencimento`; `user` ganha as
  preferências; e o enum `notificationtype` ganha `due_reminder` — que no
  Postgres **exige `ALTER TYPE` à mão**, porque `create_all` e `alembic check`
  são cegos para valor de enum.
- `pywebpush` entra em `requirements.txt`.
- `sw.js` ganha `push` e `notificationclick`, e a `VERSAO` sobe.
- Gate no `verify-build-assets.mjs`: build que perder o handler de push reprova.
- O `cron` do compose ganha uma linha no laço horário.

## O que fica de fora

**`due_date` no lançamento.** É o conserto real da imprecisão do item 1, e é uma
coluna, uma migração, um campo no formulário e uma revisão do
`payables_service`. Fora daqui para não misturar "avisar" com "mudar o que uma
conta a pagar é". Enquanto não existir, o aviso de conta a pagar carrega a
ressalva da data do lançamento.

**Silenciar por horário ("não perturbe").** O aviso sai uma vez por dia, numa
hora escolhida — o problema que o "não perturbe" resolve não existe ainda.

**Aviso por espaço compartilhado.** Hoje o aviso é de quem **paga** (o
`TransactionPayer`), seguindo o mesmo recorte do `payables_service`. Avisar o
espaço inteiro sobre a conta de um membro esbarra no ADR 0018 e é decisão de
dono, não técnica.

**Push de outros eventos** (convite recebido, acerto pedido). O encanamento fica
pronto para isso, mas cada evento novo é uma decisão de fadiga própria.
