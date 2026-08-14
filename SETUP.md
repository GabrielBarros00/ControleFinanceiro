# SETUP — Configuração e Deploy

Guia de referência para configurar o Controle Financeiro V4 em **produção** e em **dev**.

## Os dois arquivos `.env` (não confundir)

| Arquivo | Contexto | Template | Quem lê |
|---|---|---|---|
| **`/.env`** (raiz) | **PRODUÇÃO** (Docker Compose) | `/.env.example` | `docker-compose.yml` injeta nos containers |
| `/backend/.env` | **DEV local** (uvicorn direto) | `/backend/.env.example` | O backend, só quando roda fora do Docker |

- Em produção o container **ignora** o `backend/.env` (está no `.dockerignore`).
- Ambos são **gitignorados** — nunca commite um `.env`.

---

## Produção — passo a passo

> **Primeira vez numa VPS?** Este arquivo é a *referência* de cada variável.
> Para o roteiro do zero ao ar — servidor, firewall, HTTPS com Caddy ou
> Cloudflare Tunnel, primeiro acesso e backup no cron — siga
> [docs/deploy-vps.md](docs/deploy-vps.md).

```bash
cp .env.example .env
nano .env                      # preencha conforme a tabela abaixo
docker compose up --build -d
docker compose logs backend | tail -20      # confere se subiu sem recusa de config
python scripts/smoke_prod.py                # verificações automáticas (~20s)
```

Depois disso, **acesse `/register` com o e-mail que você pôs em
`SUPERADMIN_EMAIL`**. Essa primeira conta nasce superadministradora e é a única
que entra sem convite — o cadastro do site já nasce fechado (veja
[Cadastro e administração](#cadastro-e-administração)).

### Tabela de variáveis (produção)

| Variável | Obrigatória? | O que é | Como preencher |
|---|---|---|---|
| `POSTGRES_PASSWORD` | ✅ | Senha do banco | `python -c "import secrets; print(secrets.token_urlsafe(24))"` — **antes do 1º `up`** (fica gravada no volume) |
| `POSTGRES_USER` / `POSTGRES_DB` | padrão serve | Usuário/nome do banco | Deixe `cf4` / `controle_financeiro` |
| `SECRET_KEY` | ✅ | Assina os tokens de sessão | `python -c "import secrets; print(secrets.token_urlsafe(48))"` — o app **recusa subir** com chave fraca |
| `SUPERADMIN_EMAIL` | ✅ | Quem administra o site | Seu e-mail. É a **única conta que se cadastra sem convite**, e só no primeiro acesso. O app **recusa subir** sem ela |
| `APP_ENV` | ✅ | Modo do app | `production` com HTTPS; `staging` se for HTTP puro (IP local) |
| `COOKIE_SECURE` | ✅ | Cookie só via HTTPS | `True` com HTTPS; `False` se HTTP puro (senão **ninguém loga**) |
| `APP_TIMEZONE` / `TZ` | padrão serve | Fuso do calendário do app e do relógio dos containers | Mantenha os dois iguais; `America/Sao_Paulo` é o padrão |
| `FRONTEND_URL` | ✅ | URL pública do app | O endereço que as pessoas digitam. Vai nos links de email e no redirect do Google |
| `HTTP_PORT` | padrão serve | Porta do nginx | `80` (ou outra se a 80 estiver ocupada) |
| `BIND_ADDR` | ✅ se houver proxy TLS | Interface em que a porta é publicada | `127.0.0.1` quando Caddy/Traefik terminam HTTPS no host — senão o app continua respondendo em `http://` na porta direta e o TLS vira opcional. `0.0.0.0` (padrão) sem proxy |
| `COMPOSE_PROFILES` / `CLOUDFLARE_TUNNEL_TOKEN` | só com Tunnel | Ativa e autoriza o container `cloudflared` | Use `cloudflare` e o token exibido em **Networking → Tunnels**. Deixe ambos vazios nos outros tipos de deploy |
| `CORS_ORIGINS` | deixar vazio | Origens extras de CORS | Vazio = same-origin via nginx (correto) |
| `ALLOWED_HOSTS` | ✅ (em `production`) | Host(s) confiável(is) (anti-Host forjado) | Domínio(s) reais separados por vírgula. Em `APP_ENV=production` o app **recusa subir** com `*`/vazio; `localhost` já é aceito p/ o healthcheck. Em `staging` pode deixar vazio |
| `GOOGLE_CLIENT_ID` / `GOOGLE_CLIENT_SECRET` / `GOOGLE_REDIRECT_URI` | opcional | Login com Google | Ver seção [Google OAuth](#google-oauth) |
| `SMTP_*` / `EMAIL_FROM` | opcional; remetente obrigatório com SMTP | Envio de emails | Ver seção [Email](#email-smtp). Sem `SMTP_HOST` = links no log; com SMTP, use um remetente aceito pelo provedor |
| `REGISTRATION_MODE` | padrão serve | Portão de cadastro antes de haver ajuste salvo na tela | `invite_only` (recomendado), `open` ou `closed` |
| `RATE_LIMIT_ENABLED` | padrão serve | Anti força-bruta no login | `True` |
| `RATE_LIMIT_AUTH_PER_MINUTE` / `RATE_LIMIT_ACCOUNT_PER_MINUTE` | padrão serve | Tetos por minuto: por IP+rota e por conta alvo | `20` / `10`. O de IP é compartilhado por quem está atrás do mesmo Wi-Fi/CGNAT — apertá-lo tranca gente legítima. O de conta deve continuar sendo o menor |
| `ATTACHMENT_QUOTA_BYTES` / `UPLOAD_MAX_BYTES` | padrão serve | Cota por workspace / teto por arquivo | 200 MB / 5 MB; o nginx impõe teto externo de 6 MB por requisição |
| `IMPORT_MAX_ROWS` | padrão serve | Teto absoluto por importação CSV | `5000`; a tela de Administração só consegue reduzi-lo |
| `FORWARDED_ALLOW_IPS` | deixar vazio | Proxies em que o uvicorn confia p/ ler `X-Forwarded-For` | Vazio = faixas privadas (rede do Compose). Abrir para `*` devolve ao cliente o poder de forjar o próprio IP no rate limit |
| `ACCESS_TOKEN_EXPIRES_MINUTES` / `REFRESH_TOKEN_EXPIRES_DAYS` / `RESET_TOKEN_EXPIRES_MINUTES` | padrão serve | Validade de acesso, sessão e link de recuperação | `30` min / `7` dias / `30` min |
| `DB_POOL_SIZE` / `DB_MAX_OVERFLOW` | padrão serve | Conexões base e excedentes por processo | `10` / `20`; reduza se o PostgreSQL tiver limite baixo |
| `DB_POOL_TIMEOUT_SECONDS` / `DB_POOL_RECYCLE_SECONDS` | padrão serve | Espera por conexão / reciclagem do pool | `30` / `1800` segundos |
| `SQL_ECHO` | manter `False` | Log detalhado de SQL | Pode expor parâmetros sensíveis; habilite só durante diagnóstico controlado |
| `EXCHANGE_RATE_TIMEOUT_SECONDS` | padrão serve | Timeout por tentativa contra a fonte de câmbio | `4.0`; o look-back pode fazer até cinco tentativas |
| `IOF_INTERNATIONAL_CARD_RATE` | confira no deploy | Alíquota decimal para novas compras internacionais | `0.035` = 3,5%; lançamentos antigos preservam o valor já congelado |

### Decisão HTTPS vs HTTP (a mais importante)

- **Cenário A — domínio com HTTPS** (recomendado): `APP_ENV=production` + `COOKIE_SECURE=True`. Coloque um proxy TLS na frente (Caddy e Traefik emitem certificado Let's Encrypt sozinhos) apontando para a porta do `HTTP_PORT`.
- **Cenário B — rede local, sem TLS** (`http://192.168.x.x`): `APP_ENV=staging` + `COOKIE_SECURE=False`. Todo o resto (Postgres, migrações, rate limit) continua em modo produção.

**Cloudflare Tunnel no Docker.** Crie um Tunnel gerenciado no painel da
Cloudflare e, no *Public Hostname*, selecione o tipo **HTTP** e configure o
serviço como `http://frontend:8080`. Copie o token do Tunnel para
`CLOUDFLARE_TUNNEL_TOKEN` no `.env` e suba o profile opcional:

```bash
docker compose --profile cloudflare up --build -d
```

O nginx publica apenas a porta 80 no host. A porta 8080 fica na rede Docker
dedicada. O `cloudflared` recebe nela o IP fixo `172.31.255.2`, e o nginx só
converte `CF-Connecting-IP` no `X-Forwarded-For` quando **origem e porta** são,
respectivamente, esse container e `8080`. Qualquer outra origem em `8080`
recebe `403`; portanto, mesmo que alguém publique essa porta por engano, um
cliente externo não consegue forjar o IP usado no rate limit. Na porta 80,
inclusive com `BIND_ADDR=0.0.0.0`, o comportamento anterior permanece: headers
Cloudflare enviados pelo cliente são ignorados e vale o IP direto da conexão.
Não é necessária uma Transform Rule nem um segredo adicional de header.

Para não repetir `--profile cloudflare` nas atualizações, acrescente também
`COMPOSE_PROFILES=cloudflare` ao `.env`. Se a subnet `172.31.255.0/29` já for
usada pela VPS ou por uma VPN, escolha outra `/29` livre e altere em conjunto o
`ipv4_address` do `cloudflared` no Compose e o endereço confiável no
`frontend/nginx.conf`.

O token é uma credencial: proteja o arquivo com `chmod 600 .env` no servidor.
Nenhuma porta web de entrada é necessária, mas redes com egress restritivo devem
permitir TCP e UDP de saída na porta 7844 para os endpoints da Cloudflare.

Se o site deve ser acessível **somente** pelo Tunnel, use
`BIND_ADDR=127.0.0.1`. Se também quiser acesso direto pela rede, mantenha
`BIND_ADDR=0.0.0.0`.

Por quê: cookie com flag `Secure` não é enviado pelo navegador em `http://` (exceto localhost) — com a combinação errada, o login "funciona" mas a sessão nunca persiste.

### Cadastro e administração

O cadastro do site **nasce fechado**: só entra quem tem convite ([ADR 0026](docs/adr/0026-papel-de-plataforma-e-cadastro-por-convite.md)).
Sem isso, publicar o app na internet significaria deixar qualquer pessoa criar
conta no seu servidor.

**Primeiro acesso.** Vá em `{FRONTEND_URL}/register`. Enquanto o site não tiver
administrador, a tela se anuncia como **Primeiro acesso** e aceita o cadastro:
use o e-mail de `SUPERADMIN_EMAIL`. Essa conta é a única que passa sem convite, e
só enquanto não existir nenhum superadministrador — depois de criada, a janela
fecha sozinha e a mesma tela volta a exigir convite. Você entra já com o item
**Administração** no menu. Entrar com Google também funciona aqui, se você tiver
configurado o OAuth com esse mesmo endereço.

**Convidar as outras pessoas.** Em *Administração → Convites*, gere um convite
(com e-mail, e ele é enviado; sem e-mail, você copia o link). Quem entrar por ele
ganha o próprio espaço, separado do seu — para dividir despesas, convide a pessoa
depois para um workspace em *Configurações do workspace → Membros*. Usuários
comuns também podem convidar, em *Suas configurações → Convidar alguém*, dentro
de uma cota mensal.

**O que dá para configurar sem reiniciar** (em *Administração → Configurações*):

| Ajuste | Observação |
|---|---|
| Modo de cadastro | aberto, por convite (padrão) ou fechado |
| Quem pode convidar | qualquer pessoa cadastrada (padrão) ou só administradores |
| Validade e cota de convites | dias até expirar; convites por pessoa/mês |
| Anexos por workspace | em MB |
| Tamanho máximo por arquivo | teto de 6 MB — é o `client_max_body_size` do nginx, que fica **na frente** do backend |
| Linhas por importação | — |
| Rate limit de login | por IP e por conta |
| Modo manutenção | só administradores usam o site; você continua entrando para desligar |

Os quatro últimos ajustes também existem como variável de ambiente
(`ATTACHMENT_QUOTA_BYTES`, `UPLOAD_MAX_BYTES`, `IMPORT_MAX_ROWS`,
`RATE_LIMIT_*`). A ordem é **banco → `.env` → padrão embutido**: enquanto você
não gravar nada pela tela, o valor acompanha o `.env`; depois de gravar, a tela
vence, e ela mostra quais chaves ainda seguem o ambiente. `IMPORT_MAX_ROWS` é o
único que a tela só consegue **apertar** — o teto do processo é o do `.env`.

**O login com Google respeita o portão.** Autenticar com o Google prova quem a
pessoa é; não responde se ela pode ter conta neste site. Com o cadastro por
convite, um endereço sem conta e sem convite recebe a mesma recusa que receberia
no formulário. Quem já tem conta continua entrando normalmente.

**O que o administrador NÃO vê:** lançamentos, valores, cartões ou renda de
outras pessoas. A área administrativa mostra contagem, tamanho em disco, último
acesso e papel — nunca dinheiro alheio. Isso é decisão de projeto e tem teste
dedicado que reprova qualquer regressão.

**Perdeu o acesso de administrador?** O `SUPERADMIN_EMAIL` é repromovido a cada
inicialização do container — corrija o `.env` e `docker compose restart backend`.

### Google OAuth

1. Acesse <https://console.cloud.google.com/apis/credentials> (crie um projeto se não tiver).
2. **Create Credentials → OAuth client ID → Web application**.
3. Em **Authorized redirect URIs**, adicione exatamente:
   `{FRONTEND_URL}/api/v1/auth/google/callback`
   (ex.: `https://financas.seudominio.com/api/v1/auth/google/callback`)
4. Copie o **Client ID** e o **Client secret** para o `.env`, e preencha `GOOGLE_REDIRECT_URI` com a mesma URL do passo 3.
5. `docker compose up -d backend` para recarregar.

Sem preencher: o botão "Entrar com Google" avisa que está indisponível; login por email/senha funciona normalmente.

### Email (SMTP)

Sem `SMTP_HOST`, os links de **convite** e **recuperação de senha** aparecem em `docker compose logs backend` — você copia e envia manualmente.

Para envio real com Resend e domínio verificado:

```env
SMTP_HOST=smtp.resend.com
SMTP_PORT=587
SMTP_USER=resend
SMTP_PASSWORD=<API key da Resend>
SMTP_TLS=True
EMAIL_FROM=noreply@seudominio.com
```

Use a porta 587: o backend faz STARTTLS. A porta 465 usa SSL implícito e não é
suportada por esta implementação. Os registros SPF, DKIM e DMARC ficam no DNS
do domínio (por exemplo, na Cloudflare); eles não pertencem ao `.env`.

Como alternativa, para Gmail:

1. Ative verificação em 2 etapas na conta Google.
2. Gere uma **senha de app**: <https://myaccount.google.com/apppasswords>.
3. No `.env`:
   ```env
   SMTP_HOST=smtp.gmail.com
   SMTP_PORT=587
   SMTP_USER=voce@gmail.com
   SMTP_PASSWORD=<senha de app de 16 letras>
   SMTP_TLS=True
   EMAIL_FROM=voce@gmail.com
   ```
Outros provedores SMTP com STARTTLS também usam os mesmos campos.

### Depois de subir

- **Smoke test**: `python scripts/smoke_prod.py` (ou `SMOKE_BASE_URL=https://seu-dominio python scripts/smoke_prod.py`).
- **Backup — são DOIS artefatos**. O dump sozinho restaura os lançamentos com os
  **recibos quebrados**: desde o [ADR 0007](docs/adr/0007-anexos-fora-do-banco-com-hash.md)
  o conteúdo dos anexos mora no volume `attachments_data`, não no banco.

  O jeito recomendado é o **`scripts/backup.sh`**, que grava os dois, confere que
  nenhum saiu truncado e sai com código != 0 quando algo falha (é assim que o
  cron te avisa) — veja [docs/deploy-vps.md](docs/deploy-vps.md#7-backup-automático-não-pule):
  ```bash
  ./scripts/backup.sh                 # ./backups, retenção de 30 dias
  ./scripts/backup.sh /mnt/externo 60
  ```
  Os comandos equivalentes, se preferir fazer à mão:
  ```bash
  # 1. banco
  docker compose exec db pg_dump -U cf4 controle_financeiro > backup_$(date +%F).sql
  # 2. anexos
  docker run --rm -v controle_financeiro_v4_attachments_data:/data -v "$PWD":/saida alpine \
    tar czf /saida/anexos_$(date +%F).tar.gz -C /data .
  ```
  (Confira o nome real do volume com `docker volume ls`; ele leva o prefixo da pasta do projeto.)
- **Vindo de uma versão anterior a 2026-07-29?** Os anexos antigos ainda estão no
  banco. Depois de subir, mova-os para o volume — o app serve dos dois lugares
  enquanto isso, então não há indisponibilidade:
  ```bash
  docker compose exec backend python scripts/migrate_attachments_to_disk.py --dry-run
  docker compose exec backend python scripts/migrate_attachments_to_disk.py
  ```
- **Logs**: `docker compose logs -f backend`.
- **Atualizar o app**: `git pull && docker compose up --build -d` (migrações rodam sozinhas no start).

### Problemas comuns

| Sintoma | Causa provável |
|---|---|
| `backend` em restart infinito | Configuração recusada — `docker compose logs backend` mostra qual variável (SECRET_KEY fraca, COOKIE_SECURE=False com production, banco não-Postgres, SUPERADMIN_EMAIL vazio) |
| "O cadastro é apenas por convite" na tela | Esperado. Entre com o e-mail de `SUPERADMIN_EMAIL` ou peça um convite a quem já usa |
| App acessível por `http://` mesmo com HTTPS configurado | `BIND_ADDR` continua `0.0.0.0` — troque para `127.0.0.1` e suba de novo |
| Login "funciona" mas a sessão some | `COOKIE_SECURE=True` com HTTP puro — use o Cenário B |
| Link do email aponta para localhost | `FRONTEND_URL` não configurada com a URL pública |
| Porta em uso ao subir | Ajuste `HTTP_PORT` no `.env` |
| Botão Google dá erro de redirect | `GOOGLE_REDIRECT_URI` diferente do cadastrado no Google Console |

---

## Dev local — passo a passo

```bash
# Backend (porta 8000, SQLite, sem depender de Docker)
cd backend
cp .env.example .env        # os valores default já funcionam sem editar
pip install -r requirements.txt   # produção; para desenvolver: -r requirements-dev.txt
python -m uvicorn app.main:app --reload

# Frontend (porta 5173)
cd frontend
npm install
npm run dev
```

Diferenças do modo dev: SQLite (`dev.db`), cookies sem `Secure`, links de email
no console do uvicorn.

O schema é migrado no startup, mas **só se o uvicorn subir de dentro de
`backend/`**: o `APP_ENV=development` que habilita o auto-upgrade vem do
`backend/.env`, e o `.env` é lido relativo ao diretório atual. Subindo da raiz,
o processo lê o `.env` de produção e o banco fica para trás sem avisar. Depois de
trocar de branch, rode `make migrate`.

## Testes

```bash
cd backend && python -m pytest              # suíte completa (SQLite em memória)
cd frontend && npm test                     # unit (vitest)
cd frontend && npx playwright test          # E2E (sobe backend+frontend sozinho)
python scripts/smoke_prod.py                # jornada completa contra o stack do compose
```
