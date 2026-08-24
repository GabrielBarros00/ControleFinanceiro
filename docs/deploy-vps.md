# Primeiro deploy numa VPS

Guia do **zero até o app no ar**, com HTTPS via Caddy ou Cloudflare Tunnel e
backup automático.
Para *atualizar* um deploy que já existe, veja [runbook-deploy.md](runbook-deploy.md).
Para a referência de cada variável, veja [SETUP.md](../SETUP.md).

## 0. O que você precisa antes de começar

| Item | Mínimo | Observação |
|---|---|---|
| VPS | 2 GB RAM, 1 vCPU, 20 GB disco | Postgres + backend + nginx + cron. Com 1 GB o `docker compose build` do frontend (Vite) costuma morrer por falta de memória — se for o caso, veja a nota no fim |
| SO | Debian 12 / Ubuntu 22.04+ | Os comandos abaixo assumem `apt` |
| Domínio | um subdomínio | Com Caddy, crie um registro **A** para a VPS. Com Tunnel, o domínio precisa estar na Cloudflare e a rota cria o DNS |
| Portas de entrada | depende da opção HTTPS | Caddy usa 80/443; Cloudflare Tunnel não exige porta web aberta na VPS |

Com Caddy, o domínio precisa apontar para a VPS **antes** do passo 5 — a emissão
do certificado depende disso. Com Tunnel, a rota publicada no painel da
Cloudflare cuida do DNS e o `cloudflared` inicia conexões somente de saída.

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

# Firewall com Caddy: SSH e web
ufw allow OpenSSH && ufw allow 80 && ufw allow 443 && ufw --force enable

# OU, com Cloudflare Tunnel: nenhuma porta web de entrada
# ufw allow OpenSSH && ufw --force enable
```

Saia e entre de novo como `cf4` (`ssh cf4@SEU_IP`) — a participação no grupo
`docker` só vale a partir de uma sessão nova.

A porta do Compose (`HTTP_PORT`) **não** entra no firewall: ela fica publicada
só em `127.0.0.1`, alcançável pelo Caddy local ou para diagnóstico. O Tunnel
usa outra porta exclusivamente dentro da rede Docker.

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
chmod 600 .env                   # contém senhas, chaves e o token do Tunnel
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

Os valores acima servem para as duas opções de HTTPS. Se escolher Cloudflare
Tunnel, acrescente ao mesmo `.env`:

```env
COMPOSE_PROFILES=cloudflare
CLOUDFLARE_TUNNEL_TOKEN=<token copiado de Networking > Tunnels>
```

`COMPOSE_PROFILES=cloudflare` faz os comandos normais de atualização também
recriarem o conector. Quem usa Caddy, Traefik ou acesso direto deixa essas
variáveis vazias e o container `cloudflared` não é iniciado.

O Tunnel não exige porta web **de entrada**, mas o `cloudflared` precisa alcançar
a Cloudflare pela porta **7844 de saída, TCP e UDP**. O UFW padrão permite saída;
se a VPS/rede usa política de egress restritiva, libere 7844 para os endpoints
oficiais da Cloudflare antes de subir o profile.

`BIND_ADDR=127.0.0.1` é o item que mais passa batido: sem ele o aplicativo
continua respondendo em `http://SEU_IP:8890`, e o cookie `Secure` acaba viajando
por uma conexão que não é segura.

**Configure o SMTP se outras pessoas forem usar o sistema.** É opcional só na
aparência: sem ele, os links de convite e de **recuperação de senha** não são
enviados — eles saem no `docker compose logs backend`, e alguém que esqueceu a
senha depende de você ir pescar o link no log do servidor. Uma senha de app do
Gmail resolve, mas a seção 6 do `.env` também traz o exemplo da Resend. SPF,
DKIM e DMARC ficam no DNS da Cloudflare, não no `.env`.

Se for usar Google OAuth, preencha a seção 5 agora — o `GOOGLE_REDIRECT_URI`
tem de ser exatamente
`https://financas.seudominio.com/api/v1/auth/google/callback`.

---

## 4. Subir o stack

```bash
docker compose up -d --build        # o build do frontend leva alguns minutos
docker compose ps                   # com Tunnel, aparece também cloudflared
```

`db`, `backend` e `frontend` precisam aparecer `healthy`; `cron` e, quando
habilitado, `cloudflared` aparecem `Up`. Se o `backend` ficar reiniciando, a
configuração foi recusada — `docker compose logs backend` diz qual variável.

Confira que ele responde localmente:

```bash
curl -s localhost:8890/api/v1/health     # {"status":"ok",...,"database":"ok"}
```

---

## 5. Publicar com HTTPS

Escolha **uma** das opções abaixo.

### Opção A — Cloudflare Tunnel no Docker

1. No painel da Cloudflare, abra **Networking → Tunnels**, crie um Tunnel
   gerenciado e copie o token para `CLOUDFLARE_TUNNEL_TOKEN` no `.env`.
2. Dentro do Tunnel, adicione uma rota de aplicação publicada (*Public
   Hostname*) para `financas.seudominio.com`.
3. Selecione o tipo **HTTP** e informe exatamente
   `http://frontend:8080` como serviço.
4. Aplique a configuração e confira o conector:

```bash
docker compose up -d --build
docker compose ps cloudflared
docker compose logs --tail=50 cloudflared
```

A Cloudflare termina HTTPS na borda; entre ela e o nginx o tráfego usa HTTP na
rede Docker dedicada. Isso é intencional. O nginx só aceita a porta 8080 quando
a origem é o IP fixo do container `cloudflared` (`172.31.255.2`) e só nesse caso
converte `CF-Connecting-IP` no IP usado pelo backend e pelo rate limit. Uma
conexão de qualquer outra origem nessa porta recebe `403`, mesmo se alguém a
publicar posteriormente. O acesso direto na porta 80 continua ignorando headers
Cloudflare fornecidos pelo cliente.

Não habilite a Transform Rule gerenciada **Remove visitor IP headers** para este
hostname. Ela remove `CF-Connecting-IP`; sem esse cabeçalho o acesso continua
funcionando, mas todos os usuários do Tunnel parecem vir do mesmo IP do
`cloudflared` e passam a compartilhar o mesmo balde de rate limit por IP.

Mantenha `BIND_ADDR=127.0.0.1` se o Tunnel deve ser a única entrada pública.
Use `0.0.0.0` somente quando quiser oferecer também o acesso HTTP direto.

Se o Docker acusar conflito com `172.31.255.0/29`, escolha outra subnet `/29`
livre e altere **juntos** o `ipv4_address` de `cloudflared` no
`docker-compose.yml` e o IP confiável no `frontend/nginx.conf`.

### Opção B — Caddy no host

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

### Subir o MAJOR do Postgres

O único bump de dependência que o CI não consegue provar. Lá o banco nasce vazio
a cada execução, então o major passa com folga; num volume já inicializado por
uma versão anterior o container **recusa-se a subir**:

```
FATAL:  database files are incompatible with server
DETAIL: The data directory was initialized by PostgreSQL version 16,
        which is not compatible with this version 18.
```

O `PG_VERSION` dentro do volume é o que manda. Confira antes:

```bash
docker run --rm -v controlefinanceiro_postgres_data:/v:ro alpine cat /v/PG_VERSION
```

Se bate com a imagem nova, não há o que fazer. Se não bate, escolha um:

```bash
# A) O volume é descartável (dev, ou instalação sem dado que importe)
docker compose down
docker volume rm controlefinanceiro_postgres_data
docker compose up -d                       # o banco nasce de novo, na versão nova

# B) Tem dado a preservar — dump na versão ANTIGA, restore na nova
docker compose exec -T db pg_dumpall -U "$POSTGRES_USER" > /tmp/antes.sql
docker compose down
docker volume rm controlefinanceiro_postgres_data
docker compose up -d db                    # espere ficar healthy
docker compose exec -T db psql -U "$POSTGRES_USER" -d postgres < /tmp/antes.sql
docker compose up -d
```

O dump tem de sair **antes** de trocar a imagem: o `pg_dumpall` da versão nova
não lê um diretório de dados da antiga, que é justamente o problema.

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

**Rate limit atrás do proxy.** Com Cloudflare Tunnel, o nginx aceita
`CF-Connecting-IP` somente do container isolado e cada visitante mantém seu
próprio balde por IP. No acesso direto, qualquer header Cloudflare fabricado é
ignorado.

Com Caddy, o nginx do container sobrescreve
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
rodam sozinhas no start. Com `COMPOSE_PROFILES=cloudflare` no `.env`, o mesmo
comando também atualiza o Tunnel. Leia o [runbook](runbook-deploy.md) antes: ele
começa pelo backup, e por um bom motivo.
