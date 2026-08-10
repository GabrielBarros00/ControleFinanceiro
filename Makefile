# Variables
ifeq ($(OS),Windows_NT)
	VENV_BIN = .venv/Scripts
else
	VENV_BIN = .venv/bin
endif

PYTHON = $(VENV_BIN)/python
PIP = $(VENV_BIN)/pip
PYTEST = $(VENV_BIN)/pytest
RUFF = $(VENV_BIN)/ruff

# Default target
.PHONY: all
all: help

# Help
.PHONY: help
help:
	@echo "Available targets:"
	@echo "  install        - Install backend and frontend dependencies"
	@echo "  migrate        - Apply pending Alembic migrations to the local DB"
	@echo "  backend-test   - Run backend tests"
	@echo "  backend-lint   - Run backend linting (ruff)"
	@echo "  frontend-test  - Run frontend tests"
	@echo "  frontend-build - Build frontend"
	@echo "  frontend-lint  - Run frontend linting"
	@echo "  frontend-audit - Run the npm dependency vulnerability gate"
	@echo "  backend-audit  - Run the pip dependency vulnerability gate (Windows: via docker)"
	@echo "  test           - Run all tests"
	@echo "  lint           - Run all linting"
	@echo "  audit          - Run both vulnerability gates"

# Install dependencies
.PHONY: install
install:
	$(PIP) install -r backend/requirements-dev.txt
	cd frontend && npm ci

# Migrações do banco LOCAL de desenvolvimento.
#
# Existe porque o `dev.db` silenciosamente ficava para trás: `main.py` só
# auto-migra quando `APP_ENV == development`, e o `APP_ENV` vem do `.env` lido
# RELATIVO AO CWD — ou seja, o auto-upgrade só acontece se o uvicorn subir de
# dentro de `backend/`. Quem roda da raiz pega o `.env` de produção, o banco não
# migra, e a defasagem só aparece quando alguma tela quebra. (Numa auditoria o
# `dev.db` estava 15 revisões atrás do head.)
.PHONY: migrate
migrate:
	cd backend && ../$(VENV_BIN)/alembic upgrade head
	cd backend && ../$(VENV_BIN)/alembic current

# Backend targets
.PHONY: backend-test
backend-test:
	$(PYTEST) backend

# `lint` NÃO altera arquivos (antes rodava `ruff format`, que reescrevia código
# num alvo chamado "lint"). Para formatar, use `make format`.
.PHONY: backend-lint
backend-lint:
	$(RUFF) check backend

.PHONY: format
format:
	$(RUFF) format backend
	$(RUFF) check --fix backend

# Frontend targets
.PHONY: frontend-test
frontend-test:
	cd frontend && npm test

.PHONY: frontend-build
frontend-build:
	cd frontend && npm run build

.PHONY: frontend-lint
frontend-lint:
	cd frontend && npm run lint

# Gate de vulnerabilidades das dependências. Só existia no CI, então ninguém o
# rodava antes de abrir o PR.
.PHONY: frontend-audit
frontend-audit:
	cd frontend && npm run audit

# O mesmo gate do lado do Python: `pip-audit` sobre o LOCK, que é o que a imagem
# de produção instala (ver backend/Dockerfile).
#
# No Windows ele não roda nativamente, e a falha não tem nada a ver com
# vulnerabilidade: para montar a árvore de dependências o pip-audit faz um
# `pip install --dry-run` do lock, e o `uvloop` (transitivo de
# `uvicorn[standard]`) aborta a build com "uvloop does not support Windows at
# the moment". `--no-deps` não ajuda — o dry-run acontece do mesmo jeito. Por
# isso, no Windows, o alvo roda a MESMA verificação dentro do
# `python:3.12-slim`, que é a base da imagem de produção.
#
# O lock entra por STDIN em vez de um volume montado de propósito: `-v` exigiria
# um caminho absoluto no formato do Windows, e o valor de `$(CURDIR)` muda
# conforme o make (`C:/...` no mingw32-make, `/c/...` sob MSYS) — um alvo que
# funciona na máquina de quem o escreveu e falha na do vizinho. Sem montagem não
# há caminho a converter, e a linha vale igual em `cmd.exe` e em `sh`.
ifeq ($(OS),Windows_NT)
PIP_AUDIT_CMD = docker run --rm -i python:3.12-slim \
		sh -c "pip install -q pip-audit && cat > /tmp/lock.txt && pip-audit -r /tmp/lock.txt --strict" \
		< backend/requirements.lock
else
PIP_AUDIT_CMD = $(VENV_BIN)/pip-audit -r backend/requirements.lock --strict
endif

.PHONY: backend-audit
backend-audit:
	$(PIP_AUDIT_CMD)

.PHONY: audit
audit: backend-audit frontend-audit

# Global targets
.PHONY: test
test: backend-test frontend-test

.PHONY: lint
lint: backend-lint frontend-lint
