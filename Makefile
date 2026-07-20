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
	@echo "  backend-test   - Run backend tests"
	@echo "  backend-lint   - Run backend linting (ruff)"
	@echo "  frontend-test  - Run frontend tests"
	@echo "  frontend-build - Build frontend"
	@echo "  frontend-lint  - Run frontend linting"
	@echo "  test           - Run all tests"
	@echo "  lint           - Run all linting"

# Install dependencies
.PHONY: install
install:
	$(PIP) install -r backend/requirements.txt ruff pytest
	cd frontend && npm install

# Backend targets
.PHONY: backend-test
backend-test:
	$(PYTEST) backend

.PHONY: backend-lint
backend-lint:
	$(RUFF) check backend
	$(RUFF) format backend

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

# Global targets
.PHONY: test
test: backend-test frontend-test

.PHONY: lint
lint: backend-lint frontend-lint
