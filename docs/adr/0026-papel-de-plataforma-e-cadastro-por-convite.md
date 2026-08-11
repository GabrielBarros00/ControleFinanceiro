# ADR 0026 — Quem administra o site não vê o dinheiro de ninguém

**Status:** aceito (2026-08-11)
**Relacionado:** [0018](0018-privacidade-papel-e-acesso-financeiro.md) (privacidade
por membro), [0021](0021-recurso-pessoal-sem-workspace.md) (recurso pessoal),
[0010](0010-commit-unico-por-request.md) (commit único)

## Contexto

O sistema nunca soube responder *quem opera o servidor*. Sabia falar de papéis
dentro de um workspace (`WorkspaceMembership.role`: viewer, member, admin,
owner), o que responde "quem manda nesta casa" — e é uma pergunta sobre
colaboração, não sobre operação. Não havia nenhuma resposta para desativar uma
conta, ler a trilha inteira, mudar um limite ou fechar o cadastro: cada uma
dessas coisas exigia `docker compose exec` e SQL na mão.

Isso vinha junto de um defeito mais imediato: **`POST /auth/register` era
aberto**. Publicado na internet, qualquer pessoa que alcançasse a URL criava
conta. O rate limit por IP (20/min) atrasa um cadastro em massa; não impede
ninguém de entrar. Para um sistema de finanças domésticas com duas pessoas, a
porta aberta não tem nenhum benefício e tem todo o risco.

Fechar o cadastro, porém, cria um impasse: com cadastro por convite e banco
vazio, não existe quem convide. Qualquer solução para o portão precisa resolver
isso junto, ou o primeiro deploy nasce inacessível.

E há uma tensão real com o resto do projeto. Os ADRs 0018 e 0021 são o resultado
de um programa de seis ondas cujo assunto era **reduzir** quem enxerga o quê:
`financial_access` por membro, recursos pessoais fora do workspace,
`access_policy` como único portão de leitura. Introduzir um papel chamado
"superadministrador" logo depois disso é, se feito sem cuidado, desfazer tudo com
uma linha — porque a próxima funcionalidade sempre tem um bom argumento para "já
que o admin vê tudo mesmo…".

## Decisão

### 1. `platform_role` é um eixo separado, e não toca em `access_policy`

`User.platform_role` (`user` < `admin` < `superadmin`) responde "quem opera o
site". `WorkspaceMembership.role` continua respondendo "o que você faz nesta
casa". Os dois nunca se cruzam:

- `app.domain.access_policy` **não consulta** `platform_role`. Nenhuma leitura de
  lançamento, cartão, renda ou categoria muda por causa dele.
- As rotas de `/admin` devolvem contagem, tamanho, data, papel e configuração.
  Nunca valor, título ou categoria de terceiro.
- `tests/security/test_admin_sem_vazamento_financeiro.py` varre a resposta
  inteira de cada rota administrativa procurando o valor, o título e a categoria
  de um lançamento plantado. Um `SUM` sobre coluna de dinheiro em
  `/admin/overview` reprova ali, por mais inofensivo que pareça a quem o
  escreveu.

A fronteira, em uma frase: **`COUNT(*)` é operação, `SUM(amount)` é intimidade.**
Um administrador precisa saber que existem 400 lançamentos para dimensionar o
banco; nunca precisou saber que somam R$ 38.000.

Persistido como `String(20)`, não como enum nativo do Postgres — pelo motivo
documentado na revisão `e9b2c50d7a14`: valor novo em enum nativo exige
`ALTER TYPE` à mão, e as três redes que deveriam pegar a omissão (suíte em
SQLite, `alembic check`, `create_all`) são todas cegas para ela.

### 2. O cadastro nasce por convite, com uma janela de bootstrap que se fecha

`registration_mode` tem três valores — `open`, `invite_only` (padrão), `closed` —
e vale para o `POST /auth/register`. Duas espécies de token são aceitas:

- `RegistrationInvite` — tabela nova: "você pode existir neste site".
- `WorkspaceInvite` — a que já existia: "entre na minha casa". Quem foi chamado
  para dentro de um workspace obviamente pode ter conta; exigir um segundo
  convite para a mesma pessoa só produziria gente travada na tela de cadastro.

São tabelas separadas, e não um `workspace_id` anulável na antiga, porque "nulo
significa outra coisa" é a modelagem que produz vazamento — foi exatamente o que
o ADR 0021 desfez em cartão e conta.

**O portão vale para TODA porta de entrada, não só para o formulário.** A
primeira versão desta decisão fechou `POST /auth/register` e deixou
`GET /auth/google/callback` criando conta livremente: um site em `invite_only`
— ou em `closed` — continuava aceitando qualquer pessoa que tivesse uma conta
Google e alcançasse a URL. Autenticar prova *quem* alguém é; não responde se essa
pessoa pode existir neste site, e confundir as duas coisas é o que transforma um
provedor de identidade em porta dos fundos. O convite viaja **dentro do `state`
assinado** do OAuth — o Google não devolve query string nossa, então sem carregá-
lo ali o token se perderia no salto e quem foi convidado seria recusado
justamente no botão que a tela de cadastro oferece ao lado do formulário.

**A janela de bootstrap** resolve o impasse do banco vazio: o e-mail em
`SUPERADMIN_EMAIL` pode se cadastrar sem convite **enquanto não existir nenhum
superadmin no banco**. Criada a conta, ela nasce superadmin e a janela fecha
sozinha — inclusive para o mesmo endereço. `SUPERADMIN_EMAIL` é obrigatório em
`production`/`staging`: sem ele o deploy nasce sem quem o administre e sem quem
possa convidar, e o backend recusa subir em vez de entregar um sistema
inoperável.

O portão roda **antes** da checagem de e-mail duplicado. Assim, com o cadastro
fechado, um endereço já cadastrado e um inexistente respondem exatamente igual —
quem não tem convite não consegue enumerar quem tem conta.

**A janela precisa aparecer na TELA, não só existir na rota.** A primeira versão
tinha a janela no `POST` e uma tela de cadastro que escondia o formulário sempre
que o modo exigia convite — e num site recém-instalado ninguém tem convite nem
existe quem o emita. O primeiro acesso descrito no SETUP.md era, na prática,
impossível pelo navegador; passou pelos dois portões automáticos porque tanto o
`smoke_prod.py` quanto o `global-setup.ts` do e2e se cadastram pela API. Por isso
`GET /auth/registration-policy` publica `primeiro_acesso`: "este site já tem
dono?". Não revela o endereço de ninguém — quem compara é `_e_o_bootstrap`, no
POST — e a tela mostrar o formulário não abre nada, porque qualquer outro
endereço leva 403.

A lição é a de sempre neste projeto, num lugar novo: **um caminho que nenhum
teste percorre não está pronto.** A tela de cadastro não tinha teste nenhum.

**Emitir convite também é uma capacidade com mais de uma porta.** A auditoria
seguinte encontrou o mesmo defeito do OAuth, uma capacidade ao lado: enquanto
`assert_pode_cadastrar` tinha um só ponto de chamada, `assert_pode_convidar`
também tinha — `POST /me/registration-invites`. Só que um `WorkspaceInvite`
autoriza criar conta exatamente como um `RegistrationInvite` (é o que a decisão
acima diz, e é o que `_convite_de_workspace_valido` faz), e as duas rotas que o
emitem — `POST /workspaces/{id}/invites` e `.../invites/link` — não consultavam
nada. Como **todo usuário nasce `owner` do próprio "Meu Workspace"**,
`who_can_invite=admins_only` não valia nada: bastava convidar pela tela de
membros. E `max_uses` não tinha teto, então um link de workspace com
`max_uses=999999` era um cadastro público para o site inteiro, válido por até 30
dias, emitido por qualquer pessoa.

O portão passou a valer nas três rotas, e a cota conta as duas espécies de
convite — senão ela é decorativa: esgotada de um lado, continuava do outro. Duas
escolhas de desenho merecem registro:

- **Só entra na conta o convite que pode fazer o site CRESCER.** Chamar para a
  sua casa quem já tem conta não cria conta nenhuma; cobrar isso da cota
  transformaria o caso normal de um app de família em algo racionado, e
  `admins_only` passaria a significar "só o administrador monta workspace", que
  não é o que a chave promete. `created_at` do usuário comparado ao do convite
  separa os dois casos sem coluna nova.
- **O preço, assumido:** para um usuário comum com `admins_only` ligado, um 403
  e um 200 distinguem endereço com conta de endereço sem conta. Quem pergunta já
  está autenticado, e esta rota já responde diferente para quem é membro — não é
  a superfície anônima que a propriedade anti-enumeração acima protege.

### 3. Configuração de runtime é uma segunda fonte, com cascata explícita

`AppSetting` (chave/valor) guarda o que o administrador muda pela tela. A leitura
é uma cascata:

```
AppSetting (banco)  →  Settings (.env)  →  padrão embutido
```

O degrau do meio é o que faz o desenho valer: **ausência de linha significa
"acompanhe o ambiente"**. Semear a tabela na migração transformaria o `.env` em
decoração — o operador mudaria `ATTACHMENT_QUOTA_BYTES`, reiniciaria, e um valor
gravado meses antes continuaria vencendo em silêncio.

E o degrau do meio só existe se a variável **chegar ao container**: as quatro
chaves com `env=` nasceram fora do `docker-compose.yml`, o mesmo defeito do
`SMTP_TLS`, e no deploy a cascata era `AppSetting → embutido`. `tests/
test_compose_env.py` agora reprova a ausência e a divergência de padrão, porque
nenhuma outra rede enxerga isso — a suíte não sobe container, o lint não lê YAML
e o smoke só exercita o comportamento com os padrões.

**Um teto do processo não é configurável.** `import_max_rows` é validado contra
`settings.IMPORT_MAX_ROWS`, e não contra um número redondo, porque
`CommitRequest.rows` já aplica esse limite via `Field(max_length=…)` — o Pydantic
recusa o corpo antes de o handler existir. Com um teto maior aqui, a tela gravava
50.000, dizia "Configuração salva" e a importação seguia morrendo em 5.001
linhas. Pela tela o administrador só **aperta** este limite.

Credencial não entra nesta tabela. Senha de SMTP, segredo do Google e
`SECRET_KEY` seguem no ambiente: `appsetting` vai no `pg_dump`, e o dump circula
em backup, em cópia de ensaio e na máquina de quem for depurar. O que a tela
oferece sobre SMTP é diagnóstico ("está configurado?", "o envio funciona?"), não
o segredo.

O cache é de processo, seguro pela mesma restrição que o `ConnectionManager` do
WebSocket e o `RateLimiter`: `--workers 1`, fixado no Dockerfile.

### 4. Duas travas que impedem o site de ficar sem administração

Vieram de cicatriz — na Onda 10 um rebaixamento de admin *ampliava* a visão de
quem era rebaixado.

- **Hierarquia**: um `admin` não age sobre um `superadmin`, e não promove
  ninguém a `superadmin`. Sem isso, qualquer admin assumiria o site com um
  `PATCH`.
- **Último superadministrador**: não pode ser rebaixado, desativado nem removido
  — nem por ele mesmo. Sem superadmin, a configuração vira imutável e o cadastro
  por convite fica sem quem emita convite; a saída seria SQL dentro do container.
  Superadmin *inativo* não conta para essa aritmética: ele não administra nada.
- **A própria conta**: ninguém se desativa por aqui, em nenhum papel. É o único
  ato desta tela sem volta pelas mãos de quem o pratica — a sessão cai junto e o
  login seguinte é recusado por conta inativa —, e é fácil de fazer sem querer
  num interruptor ao lado do próprio nome. *Rebaixar-se* continua permitido: quem
  se rebaixa segue usando o sistema, só perde a área administrativa, e proibir
  impediria um superadministrador de passar o bastão.

Desativar uma conta **revoga as sessões** no mesmo ato. Sem isso, "inativo" não
significaria nada: o refresh token vale dias e o access token continua aceito até
expirar.

### 5. Modo manutenção libera exatamente três caminhos

`/api/v1/health` (senão o Docker reinicia o container em laço e a pausa vira
queda), `/api/v1/auth/*` (o administrador precisa conseguir entrar) e
`/api/v1/admin/*` (onde fica o botão de desligar). Um modo manutenção que tranque
o administrador do lado de fora transforma um botão de "pausar dez minutos" numa
viagem ao `docker compose exec`.

**Mas liberar `/auth/*` não é liberar o CADASTRO.** A lista existe para o
administrador *entrar*; o cadastro passava de carona, e um site em
`registration_mode=open` seguia fazendo nascer usuário, workspace e categorias
semeadas no meio da manutenção — para a pessoa entrar e receber 503 em tudo que
importa. Quem recusa é `assert_pode_cadastrar`, e não uma quarta entrada na
lista do middleware: é o ponto por onde as duas portas (formulário e Google) já
passam, e a lista trata de caminhos, não de efeitos.

A **janela de bootstrap é isenta**, e tem de ser: `maintenance_mode` é uma linha
no banco, que sobrevive a `docker compose down`. Um deploy que subisse com ela
ligada trancaria o próprio dono do lado de fora — sem conta, ninguém entra na
área administrativa; sem entrar, ninguém desliga a manutenção.

## Consequências

- Um deploy novo é fechado por padrão. Quem faz o primeiro acesso é o
  `SUPERADMIN_EMAIL`; todos os demais entram por convite — do admin ou de quem já
  está dentro, sujeito a `who_can_invite` e à cota mensal. **As duas espécies de
  convite contam**, e as três rotas que emitem passam pelo mesmo portão: um
  convite de workspace que traga alguém de fora é, para o site, a mesma coisa que
  um convite de cadastro.
- Dev, CI e e2e precisam **declarar** que querem cadastro aberto:
  `REGISTRATION_MODE=open` no `backend/.env.example` e no wrapper do e2e, e a
  fixture `cadastro_aberto_por_padrao` no `conftest`. Isso é proposital — o
  contrário (mudar o padrão conforme o `APP_ENV`) faria o CI provar um
  comportamento que produção não tem.
- Quatro limites que exigiam reinício (`attachment_quota_bytes`,
  `upload_max_bytes`, `import_max_rows`, os dois de rate limit) passam a valer na
  requisição seguinte. `upload_max_bytes` tem teto: o `client_max_body_size 6m`
  do nginx fica na frente do backend, e um valor maior seria uma configuração que
  a tela aceita e que não vale.
- `/admin` é o terceiro eixo de navegação, ao lado de "Meu" e do workspace. Só
  aparece para quem tem o papel — conveniência, não tranca: quem barra é
  `require_platform_role`, com **404** e não 403, porque a existência da área
  administrativa não é informação que um usuário comum precise confirmar.
- As rotas de `/admin` não publicam evento de WebSocket. O canal é por sala de
  **workspace**, e um evento de "usuário desativado" chegando à sala de uma casa
  contaria a todos os membros dela uma decisão administrativa que não é assunto
  daquela casa.

## Alternativas descartadas

**Admin com acesso total aos dados.** Foi considerada e recusada pelo dono do
projeto. Exigiria emendar 0018 e 0021, mexer em `access_policy` — o coração da
privacidade — e refazer os testes de segurança. Na prática significaria que a
outra pessoa da casa não tem privacidade financeira no sistema, o que é o oposto
do que o programa de seis ondas construiu.

**Fechar `/register` no nginx.** Resolveria o cadastro aberto em uma linha e
nada mais: sem papel de plataforma, sem convite, sem tela, e reabrir exigiria
editar arquivo e reconstruir a imagem.

**Um booleano `is_admin` em vez de três níveis.** Mais simples, e sem resposta
para "quem pode promover quem". A trava do último superadministrador precisa
distinguir quem opera de quem *manda em quem opera*.
