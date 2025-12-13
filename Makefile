# Makefile
SHELL := /bin/bash
.ONESHELL:
.SHELLFLAGS := -e -o pipefail -c
.DEFAULT_GOAL := help

# ------------------------------------------------------------------------------
# Environment selection
#   ENV=development | test | docker
# ------------------------------------------------------------------------------
ENV ?= development

ENV_FILE_development := .env.development
ENV_FILE_test        := .env.test
ENV_FILE_docker      := .env
ENV_FILE := $(ENV_FILE_$(ENV))

# Guardrails: expected DB name per ENV (prevents "wrong DB" operations)
EXPECTED_DB_development := arche
EXPECTED_DB_test        := arche_test
EXPECTED_DB_docker      := arche
EXPECTED_DB := $(EXPECTED_DB_$(ENV))

# ------------------------------------------------------------------------------
# Helpers
# ------------------------------------------------------------------------------
.PHONY: help
help:
	@echo ""
	@echo "Arche commands (ENV=$(ENV))"
	@echo ""
	@echo "Quality:"
	@echo "  make fix                 Ruff+Black+Mypy (fix)"
	@echo "  make check               Ruff+Black+Mypy (check)"
	@echo "  make test                Pytest (quiet) using $(ENV_FILE)"
	@echo "  make test-cov             Pytest w/ coverage using $(ENV_FILE)"
	@echo ""
	@echo "DB / Alembic (guarded):"
	@echo "  make db-print            Show resolved DB target from $(ENV_FILE)"
	@echo "  make db-guard            Fail if DB name != $(EXPECTED_DB)"
	@echo "  make psql                psql into resolved DB"
	@echo "  make alembic-up          alembic upgrade head (guarded)"
	@echo ""
	@echo "Docker compose:"
	@echo "  make up                  docker compose up -d"
	@echo "  make down                docker compose down"
	@echo "  make reset-db            docker compose down -v"
	@echo ""

.PHONY: _ensure-venv
_ensure-venv:
	@test -n "$$VIRTUAL_ENV" || (echo "Activate venv first: source .venv/bin/activate" && exit 1)

.PHONY: _ensure-env-file
_ensure-env-file:
	@test -f "$(ENV_FILE)" || (echo "Missing env file: $(ENV_FILE)" && exit 1)

# ------------------------------------------------------------------------------
# DB diagnostics + guard (bash only; no multiline if/fi)
# ------------------------------------------------------------------------------
.PHONY: db-print
db-print: _ensure-env-file
	@set -a; source "$(ENV_FILE)"; set +a; \
	url="$${DATABASE_URL:-}"; \
	url="$$(printf '%s' "$$url" | sed -E 's/^postgresql\+[^:]+:\/\//postgresql:\/\//')"; \
	url_noq="$${url%%\?*}"; url_noq="$${url_noq%%\#*}"; \
	db="$${url_noq##*/}"; \
	masked="$$(printf '%s' "$$url_noq" | sed -E 's#(://[^:/@]+):[^@]+@#\1:****@#')"; \
	echo "ENV=$(ENV)"; \
	echo "ENV_FILE=$(ENV_FILE)"; \
	echo "DATABASE_URL(masked)=$$masked"; \
	echo "DB_NAME=$$db"; \
	echo "PSQL_DSN=$$url_noq"; \
	echo "EXPECTED_DB=$(EXPECTED_DB)"

.PHONY: db-guard
db-guard: _ensure-env-file
	@set -a; source "$(ENV_FILE)"; set +a; \
	url="$${DATABASE_URL:-}"; \
	test -n "$$url" || { echo "DB guard failed: DATABASE_URL is empty after sourcing $(ENV_FILE)"; exit 1; }; \
	url="$$(printf '%s' "$$url" | sed -E 's/^postgresql\+[^:]+:\/\//postgresql:\/\//')"; \
	url_noq="$${url%%\?*}"; url_noq="$${url_noq%%\#*}"; \
	db="$${url_noq##*/}"; \
	test "$$db" = "$(EXPECTED_DB)" || { \
		echo "DB guard failed:"; \
		echo "  ENV=$(ENV)"; \
		echo "  expected=$(EXPECTED_DB)"; \
		echo "  actual=$$db"; \
		exit 1; \
	}

# ------------------------------------------------------------------------------
# Quality
# ------------------------------------------------------------------------------
.PHONY: fix
fix: _ensure-venv
	ruff check --fix .
	black .
	python -m mypy -p stacklion_api -p tests

.PHONY: check
check: _ensure-venv
	ruff check .
	black --check .
	python -m mypy -p stacklion_api -p tests

.PHONY: test
test: _ensure-venv _ensure-env-file db-guard
	@set -a; source "$(ENV_FILE)"; set +a; \
	pytest -q

.PHONY: test-cov
test-cov: _ensure-venv _ensure-env-file db-guard
	@set -a; source "$(ENV_FILE)"; set +a; \
	pytest -q --cov=stacklion_api --cov-report=term-missing

# ------------------------------------------------------------------------------
# Alembic (guarded)
# ------------------------------------------------------------------------------
.PHONY: alembic-up
alembic-up: _ensure-venv _ensure-env-file db-guard
	@set -a; source "$(ENV_FILE)"; set +a; \
	alembic -x show_url=1 upgrade head

# ------------------------------------------------------------------------------
# psql
# ------------------------------------------------------------------------------
.PHONY: psql
psql: _ensure-env-file db-guard
	@set -a; source "$(ENV_FILE)"; set +a; \
	url="$${DATABASE_URL:-}"; \
	url="$$(printf '%s' "$$url" | sed -E 's/^postgresql\+[^:]+:\/\//postgresql:\/\//')"; \
	url_noq="$${url%%\?*}"; url_noq="$${url_noq%%\#*}"; \
	exec psql "$$url_noq"

# ------------------------------------------------------------------------------
# Docker compose helpers
# ------------------------------------------------------------------------------
.PHONY: up down reset-db logs
up:
	docker compose up -d

down:
	docker compose down

reset-db:
	docker compose down -v

logs:
	@ : $${API:=api}; \
	docker compose logs -f "$$API"
