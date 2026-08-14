# Runbook de deploy

O `Dockerfile` do backend roda `alembic upgrade head` **antes** do uvicorn:

```dockerfile
CMD ["sh", "-c", "alembic upgrade head && uvicorn app.main:app ..."]
```

Isso tem uma consequência que manda no resto deste documento: **migração que falha
é container que não sobe**. Não existe janela entre "subiu a versão nova" e "migrou";
o deploy inteiro depende de a migração passar na primeira tentativa, contra o dado
real de produção.

## Antes de todo `docker compose up -d --build`

Quem usa Cloudflare Tunnel deve manter `COMPOSE_PROFILES=cloudflare` no `.env`;
assim todos os comandos `docker compose` deste runbook incluem e atualizam o
container `cloudflared` automaticamente.

### 1. Backup dos DOIS artefatos

O estado do sistema não é só o banco. Anexos moram no volume `attachments_data`
(ADR 0007), e restaurar só o Postgres devolve os lançamentos com os recibos
quebrados.

```bash
# Banco
docker compose exec -T db pg_dump -U "${POSTGRES_USER:-cf4}" \
  -d "${POSTGRES_DB:-controle_financeiro}" -Fc > backup-$(date +%F-%H%M).dump

# Anexos
docker run --rm -v controle_financeiro_v4_attachments_data:/data \
  -v "$PWD:/backup" alpine \
  tar czf "/backup/anexos-$(date +%F-%H%M).tar.gz" -C /data .
```

Confira que o dump tem tamanho plausível antes de seguir. Um `pg_dump` que falhou
ainda cria o arquivo.

### 2. Ensaie a migração numa cópia

O que quebra em produção quase nunca quebra em banco vazio — foi exatamente o caso
da `a4e8c1b90f52`, cuja versão original passava em SQLite limpo e abortava em
Postgres com dado legado (conta duplicada ainda referenciada por
`transactionpayer`). Restaure o dump num banco descartável e rode o upgrade lá
primeiro:

```bash
docker compose exec -T db createdb -U "${POSTGRES_USER:-cf4}" ensaio
docker compose exec -T db pg_restore -U "${POSTGRES_USER:-cf4}" -d ensaio < backup-....dump
docker compose run --rm \
  -e DATABASE_URL="postgresql://cf4:$POSTGRES_PASSWORD@db:5432/ensaio" \
  backend alembic upgrade head
```

Passou no ensaio, siga. Falhou, corrija a migração — nunca "tente em produção para
ver".

## Rollback

**Nem toda revisão tem `downgrade()`.** Uma migração que descarta informação não
consegue recriá-la, e um `downgrade` que devolve o schema sem o dado marca a
revisão anterior como aplicada entregando um banco que não opera — pior que não
ter rollback, porque reporta sucesso.

Revisões de sentido único conhecidas:

| Revisão | Por quê |
|---|---|
| `a4e8c1b90f52` | apaga as cinco tabelas de vínculo da Onda 2 e o `workspace_id` de cartão, conta, financiamento, renda e pagamento de fatura (ADR 0021). Quem compartilhava o quê deixa de existir como dado. |

Nelas o `downgrade()` levanta `RuntimeError` com a explicação. **O caminho de volta
é o backup:**

```bash
docker compose down
docker compose up -d db
docker compose exec -T db dropdb -U "${POSTGRES_USER:-cf4}" "${POSTGRES_DB:-controle_financeiro}"
docker compose exec -T db createdb -U "${POSTGRES_USER:-cf4}" "${POSTGRES_DB:-controle_financeiro}"
docker compose exec -T db pg_restore -U "${POSTGRES_USER:-cf4}" \
  -d "${POSTGRES_DB:-controle_financeiro}" < backup-....dump
# e a imagem da versão anterior
git checkout <tag-anterior> && docker compose up -d --build
```

Restaure os anexos junto se o intervalo teve upload.

## Depois do deploy

```bash
docker compose ps                      # todos healthy
docker compose exec backend alembic current   # bate com a head do repositório
docker compose logs --tail=50 backend
```

O `frontend` é o único container exposto ao host e tem healthcheck próprio: um
nginx que subiu sem servir deixaria o stack "up" e o usuário sem app.
