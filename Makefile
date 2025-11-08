# Make sure each recipe line starts with a real TAB character
SHELL := /bin/bash
.ONESHELL:

.PHONY: check
check:
	ruff check .
	black --check .
	mypy .
	pytest -q

.PHONY: fix
fix:
	ruff check --fix .
	black .
	mypy .

.PHONY: openapi-refresh
openapi-refresh:
	UPDATE_OPENAPI_SNAPSHOT=1 pytest -q -k openapi -s
	pre-commit run end-of-file-fixer --files tests/openapi/snapshots/openapi.json
	git add tests/openapi/snapshots/openapi.json

.PHONY: openapi-commit
openapi-commit: openapi-refresh
	pre-commit run --all-files || true
	git add -A
	pre-commit run --all-files
	git commit -m "test(openapi): refresh snapshot"

.PHONY: precommit-all
precommit-all:
	pre-commit run --all-files || true
	git add -A
	pre-commit run --all-files

# Use a standalone script for IDE-friendliness
.PHONY: openapi-diff
openapi-diff:
	python scripts/openapi_diff.py

# Snapshot refresh
.PHONY: snapshot-refresh
snapshot-refresh:
	UPDATE_OPENAPI_SNAPSHOT=1 python -m pytest -q tests/openapi/test_openapi_snapshot.py::test_openapi_snapshot_contract_is_stable
	pre-commit run end-of-file-fixer --files tests/openapi/snapshots/openapi.json
	git add tests/openapi/snapshots/openapi.json
	git commit -m "test(snapshot): refresh OpenAPI snapshot"

.PHONY: env-dev env-test env-ci check test

.PHONY: setup ci
setup:
	python -m venv .venv && . .venv/bin/activate && pip install -U pip
	pip install -e ".[dev]"
ci:
	ruff check .
	black --check .
	mypy .
	pytest -q


# Export ENVIRONMENT to pick the right .env.<env> file
env-dev:
	@export ENVIRONMENT=development; \
	echo "Using .env.development"

env-test:
	@export ENVIRONMENT=test; \
	echo "Using .env.test"

env-ci:
	@export ENVIRONMENT=ci; \
	echo "Using .env.ci (in CI, inject secrets)"

check:
	ruff check .
	mypy .

test:
	python -m pytest -q
