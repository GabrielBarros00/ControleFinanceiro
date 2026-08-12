# Primeiro deploy numa VPS

Guia do **zero até o app no ar**, com HTTPS e backup automático.
Para *atualizar* um deploy que já existe, veja [runbook-deploy.md](runbook-deploy.md).
Para a referência de cada variável, veja [SETUP.md](../SETUP.md).

## 0. O que você precisa antes de começar

| Item | Mínimo | Observação |
|---|---|---|
| VPS | 2 GB RAM, 1 vCPU, 20 GB disco | Postgres + backend + nginx + cron. Com 1 GB o `docker compose build` do frontend (Vite) costuma morrer por falta de memória — se for o caso, veja a nota no fim |
| SO | Debian 12 / Ubuntu 22.04+ | Os comandos abaixo assumem `apt` |
| Domínio | um subdomínio | ex.: `financas.seudominio.com`, com registro **A** apontando para o IP da VPS |
| Portas | 80 e 443 abertas | O Let's Encrypt valida pela 80 |

O domínio precisa estar resolvendo **antes** do passo 5 — a emissão do
certificado depende disso.

---

## 1. Preparar o servidor

```bash
ssh root@SEU_IP

# Usuário comum para rodar o app (não rode o deploy como root).
# `adduser` pergunta uma senha — defina uma: é ela que o `sudo` vai pedir.
adduser cf4
usermod -aG sudo cf4

# Leve sua chave SSH para o novo usuário, senão você só entra como root
rsync --archive --chown=cf4:cf4 ~/.ssh /home/cf4/

# Docker (script oficial)
curl -fsSL https://get.docker.com | sh
usermod -aG docker cf4

# Firewall: só SSH e web
ufw allow OpenSSH && ufw allow 80 && ufw allow 443 && ufw --force enable
```

Saia e entre de novo como `cf4` (`ssh cf4@SEU_IP`) — a participação no grupo
`docker` só vale a partir de uma sessão nova.

A porta do Compose (`HTTP_PORT`) **não** entra no firewall: ela vai ficar
publicada só em `127.0.0.1`, alcançável apenas pelo proxy local.

---

## 2. Clonar o projeto

```bash
sudo mkdir -p /opt/controle_financeiro_v4 && sudo chown cf4:cf4 /opt/controle_financeiro_v4
git clone https://github.com/SEU_USUARIO/SEU_REPO.git /opt/controle_financeiro_v4
cd /opt/controle_financeiro_v4
```

Se o repositório for **privado**, o `git clone` por HTTPS vai pedir credencial.
O caminho mais simples é gerar uma chave SSH na VPS (`ssh-keygen -t ed25519`),
colar a pública em *GitHub → Settings → SSH keys*, e clonar pelo endereço
`git@github.com:SEU_USUARIO/SEU_REPO.git`.

---

## 3. Preencher o `.env`

```bash
cp .env.example .env
# Gere os dois segredos e guarde-os:
python3 -c "import secrets; print('POSTGRES_PASSWORD=' + secrets.token_urlsafe(24))"
python3 -c "import secrets; print('SECRET_KEY=' + secrets.token_urlsafe(48))"
nano .env
```

O que **precisa** mudar em relação ao arquivo de exemplo:

```env
POSTGRES_PASSWORD=<o gerado acima>        # ANTES da primeira subida — fica gravado no volume
SECRET_KEY=<o gerado acima>
SUPERADMIN_EMAIL=voce@seudominio.com      # a conta que administra o site
APP_ENV=production
COOKIE_SECURE=True
FRONTEND_URL=https://financas.seudominio.com
ALLOWED_HOSTS=financas.seudominio.com
HTTP_PORT=8890                            # porta interna; o Caddy é quem atende 80/443
BIND_ADDR=127.0.0.1                       # <- sem isso o TLS vira opcional
APP_TIMEZONE=America/Sao_Paulo
TZ=America/Sao_Paulo
```

`BIND_ADDR=127.0.0.1` é o item que mais passa batido: sem ele o aplicativo
continua respondendo em `http://SEU_IP:8890`, e o cookie `Secure` acaba viajando
por uma conexão que não é segura.

**Configure o SMTP se outras pessoas forem usar o sistema.** É opcional só na
aparência: sem ele, os links de convite e de **recuperação de senha** não são
enviados — eles saem no `docker compose logs backend`, e alguém que esqueceu a
senha depende de você ir pescar o link no log do servidor. Uma senha de app do
Gmail resolve (seção 6 do `.env`).

Se for usar Google OAuth, preencha a seção 5 agora — o `GOOGLE_REDIRECT_URI`
tem de ser exatamente
`https://financas.seudominio.com/api/v1/auth/google/callback`.

---

## 4. Subir o stack

```bash
docker compose up -d --build        # o build do frontend leva alguns minutos
docker compose ps                   # os quatro serviços: db, backend, cron, frontend
```

Todos precisam aparecer `healthy`. Se o `backend` ficar reiniciando, a
configuração foi recusada — `docker compose logs backend` diz qual variável.

Confira que ele responde localmente:

```bash
curl -s localhost:8890/api/v1/health     # {"status":"ok",...,"database":"ok"}
```

---

## 5. HTTPS com Caddy

O `caddy` do apt padrão do Debian/Ubuntu costuma estar velho (ou nem existir,
dependendo da versão). Use o repositório oficial:

```bash
sudo apt install -y debian-keyring debian-archive-keyring apt-transport-https curl
curl -1sLf 'https://dl.cloudsmith.io/public/caddy/stable/gpg.key' \
  | sudo gpg --dearmor -o /usr/share/keyrings/caddy-stable-archive-keyring.gpg
curl -1sLf 'https://dl.cloudsmith.io/public/caddy/stable/debian.deb.txt' \
  | sudo tee /etc/apt/sources.list.d/caddy-stable.list
sudo apt update && sudo apt install -y caddy

sudo cp deploy/Caddyfile.example /etc/caddy/Caddyfile
sudo nano /etc/caddy/Caddyfile      # troque o domínio e confirme a porta (8890)
sudo systemctl reload caddy
```

O Caddy emite o certificado sozinho no primeiro acesso e renova sem cron.
Acompanhe com `sudo journalctl -u caddy -f` se algo não abrir.

Agora `https://financas.seudominio.com` deve carregar o app.

---

## 6. Criar sua conta de administrador

O cadastro do site **nasce fechado** (ADR 0026): só entra quem tem convite.
A exceção é a primeira conta.

1. Acesse `https://financas.seudominio.com/register`
2. A tela se anuncia como **Primeiro acesso** — cadastre-se com o e-mail exato
   de `SUPERADMIN_EMAIL`
3. Você entra já com **Administração** no menu; a janela de primeiro acesso
   fecha sozinha

A partir daí, convide as outras pessoas em *Administração → Convites*.

> Perdeu o acesso de administrador? O `SUPERADMIN_EMAIL` é repromovido a cada
> start: corrija o `.env` e `docker compose restart backend`.

---

## 7. Backup automático (não pule)

O estado do sistema são **dois** artefatos — o banco e o volume de anexos.
O `scripts/backup.sh` grava os dois e falha com código != 0 se qualquer um sair
truncado ou ausente (é o que faz o cron te avisar por e-mail).

```bash
chmod +x scripts/backup.sh
./scripts/backup.sh                        # teste manual: veja os dois arquivos em ./backups
crontab -e
```

```cron
0 3 * * * cd /opt/controle_financeiro_v4 && ./scripts/backup.sh >> /var/log/cf4-backup.log 2>&1
```

**Copie os backups para fora da VPS.** Um backup que mora no mesmo disco do
banco não sobrevive ao evento que costuma exigir backup. `rclone`, `scp` para
casa, ou o snapshot do provedor — qualquer um serve, desde que seja outro lugar.

E, uma vez por mês, **restaure** o dump mais recente num banco descartável para
confirmar que ele presta (o ensaio está no [runbook](runbook-deploy.md#2-ensaie-a-migração-numa-cópia)).
Backup que nunca foi restaurado não é backup.

---

## 8. Conferir que ficou de pé

```bash
docker compose ps                         # os quatro serviços healthy
docker compose exec backend alembic current   # bate com a head do repositório
curl -s https://financas.seudominio.com/api/v1/health   # database: ok
curl -sI https://financas.seudominio.com | grep -iE "strict-transport|content-security|x-frame"
```

E, na tela: entre com sua conta, crie uma despesa e confira que ela aparece.

> **Não rode o `scripts/smoke_prod.py` contra esta instância.** Ele é um gate de
> stack descartável, não de produção: cria contas e lançamentos de teste, e o
> primeiro passo dele é registrar um superadministrador pela janela de primeiro
> acesso — que aqui já está fechada desde o passo 6. Contra produção ele falha
> logo no começo, e o que ele deixaria para trás se passasse seriam dados falsos
> no seu sistema.
>
> O lugar dele é antes: contra um stack de teste (é o que o CI faz a cada push,
> no job `prod-stack`) ou localmente, com `docker compose -p teste` e um `.env`
> descartável.

---

## Notas que economizam uma tarde

**Rate limit atrás do proxy.** O nginx do container sobrescreve
`X-Forwarded-For` com o endereço de quem o alcançou — que, com o Caddy na
frente, é sempre o mesmo. Na prática o teto por IP
(`RATE_LIMIT_AUTH_PER_MINUTE`, 20/min) vira um balde **compartilhado por todo
mundo** nas rotas de login. Para um grupo pequeno isso não incomoda; se
incomodar, aumente esse valor — não o de conta. O teto por conta
(`RATE_LIMIT_ACCOUNT_PER_MINUTE`) é o que barra força bruta num alvo específico
e continua funcionando normalmente, porque não depende do IP.

Essa sobrescrita é deliberada: sem ela, `X-Forwarded-For` seria um cabeçalho
escolhido pelo cliente, e trocá-lo a cada tentativa daria um balde novo — força
bruta sem teto. Não a afrouxe sem entender o que está destrancando.

**Build morrendo por memória.** Se o `docker compose build` do frontend for
morto (`Killed`) numa VPS de 1 GB, adicione swap:

```bash
sudo fallocate -l 2G /swapfile && sudo chmod 600 /swapfile
sudo mkswap /swapfile && sudo swapon /swapfile
echo '/swapfile none swap sw 0 0' | sudo tee -a /etc/fstab
```

**Logs crescendo sem limite.** O Docker guarda o stdout dos containers
indefinidamente. Em `/etc/docker/daemon.json`:

```json
{ "log-driver": "json-file", "log-opts": { "max-size": "10m", "max-file": "3" } }
```

e `sudo systemctl restart docker`.

**Atualizar depois.** `git pull && docker compose up -d --build` — as migrações
rodam sozinhas no start. Mas leia o [runbook](runbook-deploy.md) antes: ele
começa pelo backup, e por um bom motivo.
