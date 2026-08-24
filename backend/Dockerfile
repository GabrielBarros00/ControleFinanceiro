FROM python:3.14-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

WORKDIR /app

# Só as dependências de PRODUÇÃO: pytest e afins moram em requirements-dev.txt
# e não entram na imagem.
#
# A instalação usa o COMPILADO (`requirements.txt`), não a fonte
# (`requirements.in`). As diretas sempre foram fixadas, mas as transitivas não:
# dois `docker build` do mesmo commit podiam resolver versões diferentes de
# `httpcore`, `cffi` ou `typing-extensions`, e o ambiente que passou nos testes
# não era o que ia para produção. O frontend tem `package-lock.json` desde
# sempre; isto é o equivalente.
#
# Para atualizar: mexa em `requirements.in` e regenere com `scripts/relock.sh`
# (que compila no MESMO Python da imagem — um compilado gerado noutra versão
# traz markers diferentes e pode omitir backport necessário aqui).
COPY requirements.txt ./
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

# O diretório de anexos (ADR 0007) precisa existir NA IMAGEM e pertencer ao
# appuser. Um volume nomeado montado num caminho que não existe na imagem é
# criado pelo Docker como root:root — e o processo, que roda como appuser, levava
# "permission denied" no primeiro upload de cada workspace. Criando aqui, o
# volume novo herda dono e modo deste diretório.
RUN useradd --create-home appuser \
 && mkdir -p /data/attachments \
 && chown -R appuser /app /data
USER appuser

EXPOSE 8000

# IMPORTANTE: manter --workers 1 — o ConnectionManager de WebSocket é
# in-process; com mais workers os eventos deixam de chegar a todos os
# clientes. Para escalar horizontalmente, seria preciso um broker (Redis).
#
# `--forwarded-allow-ips` NÃO pode ser '*': com ele o uvicorn entra em
# `always_trust` e aceita `X-Forwarded-For` de qualquer origem — inclusive de
# quem alcance este container por fora da rede do Compose. O default abaixo são
# as faixas privadas (o IP do nginx na rede do Compose é dinâmico, então não dá
# para fixar um endereço); quem publica o backend de outro jeito ajusta pela
# variável, sem rebuild. O nginx já sobrescreve o cabeçalho — isto é a segunda
# tranca, não a primeira.
CMD ["sh", "-c", "alembic upgrade head && uvicorn app.main:app --host 0.0.0.0 --port 8000 --proxy-headers --forwarded-allow-ips \"${FORWARDED_ALLOW_IPS:-127.0.0.1,10.0.0.0/8,172.16.0.0/12,192.168.0.0/16}\" --workers 1"]
