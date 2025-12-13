# migrations/env.py
# Copyright (c)
# SPDX-License-Identifier: MIT
"""Alembic Environment (migrations/env.py)

Purpose:
    Configure Alembic for arche’s SQLAlchemy models with safe, deterministic
    behavior across offline and online (async) migration runs.

Design:
    - Loads env vars from .env + .env.<ENVIRONMENT> (without overriding exported vars).
    - Loads the database URL from environment variables or alembic.ini.
    - Refuses to run if ENVIRONMENT is missing (prevents “wrong DB” footguns).
    - Enforces an allowlist of DB names per ENVIRONMENT (test/dev safety fuse).
    - Uses the project Declarative Base for autogenerate (`target_metadata`).
    - Supports async engines for “online” migrations while keeping “offline”
      output stable and deterministic.
    - Stores the Alembic version table deterministically in public.alembic_version
      with VARCHAR(128) to support long revision ids.
    - Emits masked connection information to the log (no credentials).
    - Cleaned for Ruff and mypy: imports at top (E402), no undefined names (F821),
      and no unused locals (F841).

Environment variables:
    ENVIRONMENT                 Required. One of: "test", "development", "docker" (extendable).
    DATABASE_URL                Primary database URL (preferred).
    SQLALCHEMY_DATABASE_URI     Fallback database URL.
    ECHO_SQL                    If "1", enable SQL echo in online runs.
    ALEMBIC_SHOW_URL            If "1", log masked URL during runs.

Usage:
    # Offline (SQL script):
    ENVIRONMENT=test alembic -x show_url=1 upgrade head --sql

    # Online (apply to DB):
    ENVIRONMENT=test alembic -x show_url=1 upgrade head
"""

from __future__ import annotations

import asyncio
import logging
import logging.config
import os
from collections.abc import Mapping
from pathlib import Path
from typing import Any
from urllib.parse import urlparse, urlunparse

from alembic import context
from sqlalchemy import pool
from sqlalchemy.engine import Connection
from sqlalchemy.ext.asyncio import AsyncEngine, create_async_engine

from stacklion_api.infrastructure.database.models import ref as _ref_models  # noqa: F401
from stacklion_api.infrastructure.database.models import sec as _sec_models  # noqa: F401
from stacklion_api.infrastructure.database.models.base import metadata as BaseMetadata

try:
    from dotenv import load_dotenv
except Exception:  # pragma: no cover
    load_dotenv = None  # type: ignore[assignment]


# -----------------------------------------------------------------------------
# Logging configuration
# -----------------------------------------------------------------------------
config = context.config

if config.config_file_name is not None:
    logging.config.fileConfig(config.config_file_name)

logger = logging.getLogger("alembic.env")


# -----------------------------------------------------------------------------
# Constants
# -----------------------------------------------------------------------------
_VERSION_TABLE = "alembic_version"
_VERSION_TABLE_SCHEMA = "public"


# -----------------------------------------------------------------------------
# Env loading
# -----------------------------------------------------------------------------
def _load_env_files() -> None:
    """Load .env and .env.<ENVIRONMENT> from repo root (no override).

    This makes `alembic upgrade head` behave consistently with your application
    and test setup without requiring manual `export DATABASE_URL=...` every time.

    Precedence:
      1) already-exported env vars (never overwritten)
      2) .env.<ENVIRONMENT>
      3) .env
    """
    if load_dotenv is None:
        return

    root = Path(__file__).resolve().parents[1]

    # Base .env (lowest priority)
    base = root / ".env"
    if base.exists():
        load_dotenv(base, override=False)

    env = (os.getenv("ENVIRONMENT") or "").strip().lower()
    if env:
        env_file = root / f".env.{env}"
        if env_file.exists():
            load_dotenv(env_file, override=False)


_load_env_files()


# -----------------------------------------------------------------------------
# Helpers
# -----------------------------------------------------------------------------
def _xargs() -> Mapping[str, str]:
    """Return Alembic -x key=value arguments as a mapping."""
    return dict(getattr(config, "x", {}) or {})


def _mask_url(url: str) -> str:
    """Return a masked representation of a database URL for safe logging."""
    try:
        parts = urlparse(url)
        user = parts.username or ""
        host = parts.hostname or ""
        port = f":{parts.port}" if parts.port else ""
        auth = f"{user}:****@" if user else ""
        netloc_masked = f"{auth}{host}{port}"
        return urlunparse((parts.scheme, netloc_masked, parts.path or "", "", "", ""))
    except Exception as exc:  # pragma: no cover
        logger.debug("url_mask_failed", extra={"reason": str(exc)})
        return "<masked>"


def _get_db_url() -> str:
    """Resolve the database URL from environment or alembic.ini.

    Resolution order:
        1) `DATABASE_URL`
        2) `SQLALCHEMY_DATABASE_URI`
        3) alembic.ini -> sqlalchemy.url

    Raises:
        RuntimeError: If no database URL can be resolved.
    """
    env_url = os.getenv("DATABASE_URL") or os.getenv("SQLALCHEMY_DATABASE_URI")
    if env_url:
        return env_url

    ini_url = config.get_main_option("sqlalchemy.url")
    if ini_url:
        return ini_url

    raise RuntimeError(
        "Database URL not configured (DATABASE_URL/SQLALCHEMY_DATABASE_URI/sqlalchemy.url)."
    )


def _require_environment() -> str:
    """Require ENVIRONMENT to be set to prevent accidental migrations."""
    env = (os.getenv("ENVIRONMENT") or "").strip().lower()
    if not env:
        raise RuntimeError(
            "ENVIRONMENT is required for migrations (e.g., ENVIRONMENT=test). "
            "Refusing to run without an explicit environment."
        )
    return env


def _assert_safe_db(url: str, *, env: str) -> None:
    """Refuse to run migrations against unexpected DBs for the given ENVIRONMENT.

    This prevents the classic footgun: migrating the wrong database because a URL
    was sourced from the wrong env file or your shell.
    """
    parsed = urlparse(url)
    dbname = (parsed.path or "").lstrip("/")

    allowed_by_env: dict[str, set[str]] = {
        # Local + CI tests
        "test": {"arche_test"},
        # Local dev (host or docker published port)
        "development": {"arche"},
        # Compose / container envs should still target the same logical DB name
        "docker": {"arche"},
    }

    allowed = allowed_by_env.get(env)
    if allowed is None:
        raise RuntimeError(
            f"Unsupported ENVIRONMENT={env!r} for migrations. "
            f"Supported: {sorted(allowed_by_env)}"
        )

    if dbname not in allowed:
        raise RuntimeError(
            "Refusing to run migrations against an unexpected database.\n"
            f"ENVIRONMENT={env!r}\n"
            f"database={dbname!r}\n"
            f"allowed={sorted(allowed)}\n"
            f"url={_mask_url(url)}"
        )


def _maybe_log_url(url: str) -> None:
    x = _xargs()
    if x.get("show_url") == "1" or os.getenv("ALEMBIC_SHOW_URL") == "1":
        logger.info("Using DATABASE_URL (masked): %s", _mask_url(url))


# Alembic’s target metadata used for autogenerate.
target_metadata = BaseMetadata


# -----------------------------------------------------------------------------
# Offline migrations
# -----------------------------------------------------------------------------
def run_migrations_offline() -> None:
    """Run migrations in 'offline' mode (SQL script output)."""
    env = _require_environment()
    url = _get_db_url()
    _assert_safe_db(url, env=env)
    _maybe_log_url(url)

    context.configure(
        url=url,
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
        compare_type=True,
        compare_server_default=True,
        include_schemas=True,
        # Deterministic Alembic bookkeeping table location/shape
        version_table=_VERSION_TABLE,
        version_table_schema=_VERSION_TABLE_SCHEMA,
    )

    with context.begin_transaction():
        context.run_migrations()


# -----------------------------------------------------------------------------
# Online migrations (async engine)
# -----------------------------------------------------------------------------
def _online_engine_kwargs() -> dict[str, Any]:
    """Return keyword arguments for creating an async engine."""
    echo_sql = (os.getenv("ECHO_SQL") == "1") or (
        (config.get_main_option("echo_sql") or "").strip().lower() == "true"
    )
    return {
        "echo": echo_sql,
        "poolclass": pool.NullPool,
    }


def _configure_and_run(connection: Connection) -> None:
    """Configure Alembic context with a live connection and run migrations."""
    context.configure(
        connection=connection,
        target_metadata=target_metadata,
        compare_type=True,
        compare_server_default=True,
        include_schemas=True,
        # Deterministic Alembic bookkeeping table location/shape
        version_table=_VERSION_TABLE,
        version_table_schema=_VERSION_TABLE_SCHEMA,
    )

    with context.begin_transaction():
        context.run_migrations()


async def _run_migrations_async() -> None:
    """Run migrations in 'online' mode using an async engine."""
    env = _require_environment()
    url = _get_db_url()
    _assert_safe_db(url, env=env)
    _maybe_log_url(url)

    connectable: AsyncEngine = create_async_engine(url, **_online_engine_kwargs())

    async with connectable.connect() as connection:
        await connection.run_sync(_configure_and_run)

    await connectable.dispose()


def run_migrations_online() -> None:
    """Entry point used by Alembic for online migrations (async safe)."""
    asyncio.run(_run_migrations_async())


# -----------------------------------------------------------------------------
# Entrypoint
# -----------------------------------------------------------------------------
if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
