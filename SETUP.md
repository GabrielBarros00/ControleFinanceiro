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

```bash
cp .env.example .env
nano .env                      # preencha conforme a tabela abaixo
docker compose up --build -d
docker compose logs backend | tail -20      # confere se subiu sem recusa de config
python scripts/smoke_prod.py                # 36 verificações automáticas (~20s)
```

### Tabela de variáveis (produção)

| Variável | Obrigatória? | O que é | Como preencher |
|---|---|---|---|
| `POSTGRES_PASSWORD` | ✅ | Senha do banco | `python -c "import secrets; print(secrets.token_urlsafe(24))"` — **antes do 1º `up`** (fica gravada no volume) |
| `POSTGRES_USER` / `POSTGRES_DB` | padrão serve | Usuário/nome do banco | Deixe `cf4` / `controle_financeiro` |
| `SECRET_KEY` | ✅ | Assina os tokens de sessão | `python -c "import secrets; print(secrets.token_urlsafe(48))"` — o app **recusa subir** com chave fraca |
| `APP_ENV` | ✅ | Modo do app | `production` com HTTPS; `staging` se for HTTP puro (IP local) |
| `COOKIE_SECURE` | ✅ | Cookie só via HTTPS | `True` com HTTPS; `False` se HTTP puro (senão **ninguém loga**) |
| `FRONTEND_URL` | ✅ | URL pública do app | O endereço que as pessoas digitam. Vai nos links de email e no redirect do Google |
| `HTTP_PORT` | padrão serve | Porta do nginx | `80` (ou outra se a 80 estiver ocupada) |
| `CORS_ORIGINS` | deixar vazio | Origens extras de CORS | Vazio = same-origin via nginx (correto) |
| `ALLOWED_HOSTS` | ✅ (em `production`) | Host(s) confiável(is) (anti-Host forjado) | Domínio(s) reais separados por vírgula. Em `APP_ENV=production` o app **recusa subir** com `*`/vazio; `localhost` já é aceito p/ o healthcheck. Em `staging` pode deixar vazio |
| `GOOGLE_CLIENT_ID` / `SECRET` / `REDIRECT_URI` | opcional | Login com Google | Ver seção [Google OAuth](#google-oauth) |
| `SMTP_*` / `EMAIL_FROM` | opcional | Envio de emails | Ver seção [Email](#email-smtp). Vazio = links no log |
| `RATE_LIMIT_ENABLED` | padrão serve | Anti força-bruta no login | `True` |
| `RATE_LIMIT_AUTH_PER_MINUTE` / `_ACCOUNT_` | padrão serve | Tetos por minuto: por IP+rota e por conta alvo | `20` / `10`. O de IP é compartilhado por quem está atrás do mesmo Wi-Fi/CGNAT — apertá-lo tranca gente legítima. O de conta deve continuar sendo o menor |
| `FORWARDED_ALLOW_IPS` | deixar vazio | Proxies em que o uvicorn confia p/ ler `X-Forwarded-For` | Vazio = faixas privadas (rede do Compose). Abrir para `*` devolve ao cliente o poder de forjar o próprio IP no rate limit |

### Decisão HTTPS vs HTTP (a mais importante)

- **Cenário A — domínio com HTTPS** (recomendado): `APP_ENV=production` + `COOKIE_SECURE=True`. Coloque um proxy TLS na frente (Caddy e Traefik emitem certificado Let's Encrypt sozinhos) apontando para a porta do `HTTP_PORT`.
- **Cenário B — rede local, sem TLS** (`http://192.168.x.x`): `APP_ENV=staging` + `COOKIE_SECURE=False`. Todo o resto (Postgres, migrações, rate limit) continua em modo produção.

Por quê: cookie com flag `Secure` não é enviado pelo navegador em `http://` (exceto localhost) — com a combinação errada, o login "funciona" mas a sessão nunca persiste.

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

Para envio real com Gmail:
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
Qualquer provedor SMTP serve (Resend, Brevo, Mailgun...) — mesmos campos.

### Depois de subir

- **Smoke test**: `python scripts/smoke_prod.py` (ou `SMOKE_BASE_URL=https://seu-dominio python scripts/smoke_prod.py`).
- **Backup — são DOIS artefatos** (agende os dois no mesmo cron). O dump sozinho
  restaura os lançamentos com os **recibos quebrados**: desde o [ADR 0007](docs/adr/0007-anexos-fora-do-banco-com-hash.md)
  o conteúdo dos anexos mora no volume `attachments_data`, não no banco.
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
| `backend` em restart infinito | Configuração recusada — `docker compose logs backend` mostra qual variável (SECRET_KEY fraca, COOKIE_SECURE=False com production, banco não-Postgres) |
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
