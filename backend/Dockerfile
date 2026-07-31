FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

WORKDIR /app

# Só as dependências de PRODUÇÃO: pytest e afins moram em requirements-dev.txt
# e não entram na imagem.
#
# A instalação usa o LOCK, não o requirements.txt. As diretas sempre foram
# fixadas, mas as transitivas não: dois `docker build` do mesmo commit podiam
# resolver versões diferentes de `httpcore`, `cffi` ou `typing-extensions`, e o
# ambiente que passou nos testes não era o que ia para produção. O frontend tem
# `package-lock.json` desde sempre; isto é o equivalente.
#
# Para atualizar: mexa em `requirements.txt` e regenere com
#   docker run --rm -v "$PWD:/src" -w /src python:3.12-slim \
#     sh -c "pip install pip-tools && pip-compile --output-file=requirements.lock --strip-extras requirements.txt"
# (no MESMO Python da imagem — um lock gerado noutra versão traz markers
# diferentes e pode omitir backport necessário aqui).
COPY requirements.txt requirements.lock ./
RUN pip install --no-cache-dir -r requirements.lock

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
CMD ["sh", "-c", "alembic upgrade head && uvicorn app.main:app --host 0.0.0.0 --port 8000 --proxy-headers --forwarded-allow-ips '*' --workers 1"]
