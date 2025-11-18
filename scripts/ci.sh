#!/usr/bin/env bash
set -euo pipefail

# ---------------------------------------------------------------------------
# Canonical CI/Test harness
#
# This script is the single source of truth for:
#   • Formatting (black)
#   • Linting (ruff)
#   • Typing (mypy)
#   • Tests (pytest + coverage via pyproject addopts)
#
# CI calls this script. You call this script locally before pushing.
# ---------------------------------------------------------------------------

# Behave like the CI/test environment.
export ENVIRONMENT=test
export PYTHONUNBUFFERED=1

# Match .env.tests and CI configuration exactly.
export DATABASE_URL="postgresql+asyncpg://stacklion:stacklion@127.0.0.1:5432/stacklion_test"
export REDIS_URL="redis://127.0.0.1:6379/2"

# 1) Format (no auto-fix in CI harness)
black --check .

# 2) Lint
ruff check .

# 3) Type-check
mypy -p stacklion_api -p tests

# 4) Tests
# Pytest picks up addopts (including coverage + cov-fail-under) from pyproject.toml
python -m pytest
