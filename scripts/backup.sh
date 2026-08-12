#!/usr/bin/env bash
#
# Backup dos DOIS artefatos que formam o estado do sistema.
#
# O dump do Postgres sozinho NÃO é um backup completo: desde o ADR 0007 o
# conteúdo dos anexos mora no volume `attachments_data`, fora do banco.
# Restaurar só o banco devolve os lançamentos com os recibos quebrados — e isso
# só se descobre no dia em que alguém procura o comprovante.
#
# Uso (na raiz do projeto, no HOST — não dentro de um container):
#     ./scripts/backup.sh                  # grava em ./backups
#     ./scripts/backup.sh /mnt/externo 30  # destino e retenção em dias
#
# No cron do servidor (todo dia às 3h; a saída vai para o log do cron, e um
# backup que falhou vira e-mail do cron porque este script sai com código != 0):
#     0 3 * * * cd /opt/controle_financeiro_v4 && ./scripts/backup.sh >> /var/log/cf4-backup.log 2>&1
#
# IMPORTANTE: backup que nunca foi restaurado não é backup. Uma vez por mês,
# restaure o dump mais recente num banco descartável e confira que a aplicação
# sobe (o ensaio está em docs/runbook-deploy.md).

set -euo pipefail

DESTINO="${1:-./backups}"
RETENCAO_DIAS="${2:-30}"
CARIMBO="$(date +%F-%H%M)"

cd "$(dirname "$0")/.."

# O `.env` traz POSTGRES_USER/DB. Lido de forma tolerante: linhas de comentário e
# valores com `=` no meio (senhas base64) não podem quebrar a leitura.
if [ -f .env ]; then
  POSTGRES_USER="$(grep -E '^POSTGRES_USER=' .env | head -1 | cut -d= -f2- || true)"
  POSTGRES_DB="$(grep -E '^POSTGRES_DB=' .env | head -1 | cut -d= -f2- || true)"
fi
POSTGRES_USER="${POSTGRES_USER:-cf4}"
POSTGRES_DB="${POSTGRES_DB:-controle_financeiro}"

mkdir -p "$DESTINO"

echo "==> Backup $CARIMBO -> $DESTINO"

# ---------------------------------------------------------------------------
# 1) Banco
# ---------------------------------------------------------------------------
# `-Fc` (formato custom) e não SQL puro: permite `pg_restore` seletivo e sai
# comprimido. `exec -T` porque o cron não tem TTY.
ARQ_DB="$DESTINO/banco-$CARIMBO.dump"
docker compose exec -T db pg_dump -U "$POSTGRES_USER" -d "$POSTGRES_DB" -Fc > "$ARQ_DB"

# Um `pg_dump` que falhou no meio AINDA deixa o arquivo criado — o runbook
# alerta para isso e a conferência era manual ("confira que tem tamanho
# plausível"). Aqui ela é automática: menos de 1 KB não é um banco desta
# aplicação, é um dump abortado, e seguir adiante apagaria backups bons na
# etapa de retenção lá embaixo.
TAM_DB=$(wc -c < "$ARQ_DB")
if [ "$TAM_DB" -lt 1024 ]; then
  echo "ERRO: dump do banco tem $TAM_DB bytes — abortado. Backup NÃO confiável." >&2
  rm -f "$ARQ_DB"
  exit 1
fi
echo "    banco:  $ARQ_DB ($TAM_DB bytes)"

# ---------------------------------------------------------------------------
# 2) Anexos
# ---------------------------------------------------------------------------
# O nome do volume leva o prefixo do projeto do Compose (o nome da pasta, ou o
# que estiver em `-p`/COMPOSE_PROJECT_NAME). Perguntar ao próprio Compose evita
# o palpite `controle_financeiro_v4_attachments_data`, que fica errado assim que
# alguém clona em outra pasta.
VOLUME="$(docker compose ps -q backend | head -1 \
  | xargs -r docker inspect -f '{{range .Mounts}}{{if eq .Destination "/data/attachments"}}{{.Name}}{{end}}{{end}}')"

if [ -z "$VOLUME" ]; then
  echo "ERRO: volume de anexos não encontrado (o stack está no ar?)." >&2
  exit 1
fi

ARQ_ANEXOS="$DESTINO/anexos-$CARIMBO.tar.gz"
docker run --rm -v "$VOLUME:/data:ro" -v "$(cd "$DESTINO" && pwd):/saida" alpine \
  tar czf "/saida/$(basename "$ARQ_ANEXOS")" -C /data .

# A MESMA conferência do dump, e pelo mesmo motivo — só que aqui ela pega um
# caso a mais: o `docker run` acima pode terminar com código 0 e mesmo assim não
# deixar arquivo nenhum no host, se a montagem de `/saida` não apontar para onde
# se espera (é o que acontece ao rodar este script no Git Bash do Windows, onde
# o caminho é reescrito). Sem esta checagem o script imprimia "Backup concluído"
# com o arquivo de anexos ausente e seguia para a retenção — apagando backups
# bons por causa de um que não existiu. Um tar.gz de volume VAZIO é legítimo e
# tem ~45 bytes, então o piso é baixo de propósito: o que se testa aqui é
# "existe e não está truncado", não "tem conteúdo".
if [ ! -s "$ARQ_ANEXOS" ]; then
  echo "ERRO: arquivo de anexos não foi gravado em $ARQ_ANEXOS — backup incompleto." >&2
  echo "      (no Windows, rode este script no servidor Linux; o mount de /saida não" >&2
  echo "       sobrevive à reescrita de caminho do Git Bash.)" >&2
  # O dump do banco fica: ele é válido e foi conferido. Apagá-lo por causa da
  # falha do OUTRO artefato seria jogar fora o backup que deu certo. Fica sem
  # par, e é justamente por isso que o script sai com erro em vez de avisar
  # baixinho — a retenção não roda, e o par incompleto salta aos olhos no log.
  echo "      O dump do banco foi mantido em $ARQ_DB (sem o par de anexos)." >&2
  exit 1
fi
echo "    anexos: $ARQ_ANEXOS ($(wc -c < "$ARQ_ANEXOS") bytes, volume $VOLUME)"

# ---------------------------------------------------------------------------
# 3) Retenção
# ---------------------------------------------------------------------------
# Só roda depois de os dois artefatos acima terem sido gravados e conferidos:
# com `set -e`, uma falha lá em cima encerra o script antes daqui. Apagar o
# histórico logo após um backup que falhou é como se perde tudo de uma vez.
if [ "$RETENCAO_DIAS" -gt 0 ]; then
  find "$DESTINO" -maxdepth 1 -name 'banco-*.dump'   -mtime "+$RETENCAO_DIAS" -delete
  find "$DESTINO" -maxdepth 1 -name 'anexos-*.tar.gz' -mtime "+$RETENCAO_DIAS" -delete
  echo "    retenção: mantidos os últimos $RETENCAO_DIAS dias"
fi

echo "==> Backup concluído."
