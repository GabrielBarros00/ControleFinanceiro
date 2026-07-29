FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

WORKDIR /app

# Só as dependências de PRODUÇÃO: pytest e afins moram em requirements-dev.txt
# e não entram na imagem.
COPY requirements.txt .
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
CMD ["sh", "-c", "alembic upgrade head && uvicorn app.main:app --host 0.0.0.0 --port 8000 --proxy-headers --forwarded-allow-ips '*' --workers 1"]
