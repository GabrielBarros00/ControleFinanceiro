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
	@echo "  frontend-audit - Run the dependency vulnerability gate"
	@echo "  test           - Run all tests"
	@echo "  lint           - Run all linting"

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

# Global targets
.PHONY: test
test: backend-test frontend-test

.PHONY: lint
lint: backend-lint frontend-lint
