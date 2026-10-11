# CloudOps Copilot — tareas de desarrollo. `make help` lista los objetivos.
.DEFAULT_GOAL := help
SHELL := /bin/bash

BACKEND := backend
FRONTEND := frontend
TF := infra/terraform
PY := $(BACKEND)/.venv/bin/python

.PHONY: help setup setup-backend setup-frontend dev test test-web test-e2e-docker test-integration lint build \
        docker-up docker-down tf-fmt tf-validate smoke deploy destroy clean

help: ## Muestra esta ayuda
	@grep -E '^[a-zA-Z_-]+:.*?## ' $(MAKEFILE_LIST) | awk 'BEGIN {FS = ":.*?## "}; {printf "  \033[36m%-18s\033[0m %s\n", $$1, $$2}'

setup: setup-backend setup-frontend ## Instala dependencias de backend y frontend

setup-backend: ## Crea el virtualenv e instala dependencias del backend
	cd $(BACKEND) && python3 -m venv .venv && .venv/bin/pip install -q -r requirements.txt -r requirements-dev.txt
	@test -f $(BACKEND)/.env || cp $(BACKEND)/.env.example $(BACKEND)/.env

setup-frontend: ## Instala dependencias del frontend
	npm ci --prefix $(FRONTEND) --no-audit --no-fund

dev: ## Levanta backend (:8000) y frontend (:5173)
	./scripts/dev.sh

test: ## Pruebas unitarias del backend (no tocan Azure)
	cd $(BACKEND) && .venv/bin/python -m pytest

test-web: ## Pruebas del panel: Vitest y E2E con Playwright (sin capturas)
	cd $(FRONTEND) && npm test && npm run test:e2e

test-e2e-docker: ## E2E completas con regresión visual, en la imagen de Playwright (Docker)
	cd $(FRONTEND) && npm run test:e2e:docker

test-integration: ## Prueba de fidelidad KQL contra un tenant real (requiere credenciales)
	cd $(BACKEND) && .venv/bin/python tests/integration/test_inventory_kpis.py

lint: ## Ruff (backend) y ESLint (frontend)
	cd $(BACKEND) && .venv/bin/ruff check app tests
	npm run lint --prefix $(FRONTEND)

build: ## Compila el frontend
	npm run build --prefix $(FRONTEND)

docker-up: ## Levanta la plataforma con Docker Compose
	docker compose up --build

docker-down: ## Detiene Docker Compose
	docker compose down

tf-fmt: ## Formatea el codigo Terraform
	terraform -chdir=$(TF) fmt -recursive

tf-validate: ## Valida Terraform sin backend remoto
	terraform -chdir=$(TF) init -backend=false -input=false >/dev/null && terraform -chdir=$(TF) validate

smoke: ## Prueba de humo del API desplegado (token de Azure CLI)
	./scripts/smoke-test.sh

deploy: ## Despliega infraestructura y aplicacion en Azure
	./scripts/deploy.sh

destroy: ## Destruye la infraestructura (pide confirmacion)
	./scripts/destroy.sh

clean: ## Borra artefactos locales
	rm -rf $(FRONTEND)/dist $(BACKEND)/.pytest_cache $(BACKEND)/.ruff_cache
	find . -name __pycache__ -not -path '*/.venv/*' -exec rm -rf {} +
