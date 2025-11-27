"""Alembic Environment (migrations/env.py)

Purpose:
    Configure Alembic for Stacklion’s SQLAlchemy models with safe, deterministic
    behavior across offline and online (async) migration runs.

Design:
    - Loads the database URL from environment variables or alembic.ini.
    - Uses the project Declarative Base for autogenerate (`target_metadata`).
    - Supports async engines for “online” migrations while keeping “offline”
      output stable and deterministic.
    - Emits masked connection information to the log (no credentials).
    - Cleaned for Ruff and mypy: imports at top (E402), no undefined names (F821),
      and no unused locals (F841).

Environment variables:
    DATABASE_URL                Primary database URL (preferred).
    SQLALCHEMY_DATABASE_URI     Fallback database URL.
    ECHO_SQL                    If "1", enable SQL echo in online runs.
    ALEMBIC_SHOW_URL            If "1", log masked URL during runs.

Usage:
    # Offline (SQL script):
    alembic -x show_url=1 upgrade head --sql

    # Online (apply to DB):
    alembic -x show_url=1 upgrade head
"""

from __future__ import annotations

import logging
import logging.config
import os
from collections.abc import Mapping
from typing import Any

from alembic import context
from sqlalchemy import pool
from sqlalchemy.engine import Connection
from sqlalchemy.ext.asyncio import AsyncEngine, create_async_engine

# Import your declarative Base from the application package.
# Ensure PYTHONPATH includes "src" (pyproject/mypy_path) so this resolves.
from stacklion_api.infrastructure.database.models.base import (
    metadata as BaseMetadata,
)

# -----------------------------------------------------------------------------
# Logging configuration
# -----------------------------------------------------------------------------
config = context.config

if config.config_file_name is not None:
    logging.config.fileConfig(config.config_file_name)

logger = logging.getLogger("alembic.env")


# -----------------------------------------------------------------------------
# Helpers
# -----------------------------------------------------------------------------
def _xargs() -> Mapping[str, str]:
    """Return Alembic -x key=value arguments as a mapping.

    Returns:
        Mapping[str, str]: Extra arguments passed with `alembic -x`.
    """
    return dict(getattr(config, "x", {}) or {})


def _mask_url(url: str) -> str:
    """Return a masked representation of a database URL for safe logging.

    The masking hides credentials while keeping enough host/path information to
    be useful in diagnostics.

    Args:
        url: Full database URL string.

    Returns:
        str: Masked URL string.
    """
    try:
        from urllib.parse import urlparse, urlunparse

        parts = urlparse(url)
        # Mask username/password if present
        user = parts.username or ""
        host = parts.hostname or ""
        port = f":{parts.port}" if parts.port else ""
        auth = f"{user}:****@" if user else ""
        netloc_masked = f"{auth}{host}{port}"
        masked = urlunparse((parts.scheme, netloc_masked, parts.path or "", "", "", ""))
        return masked
    except Exception as exc:  # pragma: no cover - defensive
        logger.debug("url_mask_failed", extra={"reason": str(exc)})
        return "<masked>"


def _get_db_url() -> str:
    """Resolve the database URL from environment or alembic.ini.

    Resolution order:
        1) `DATABASE_URL`
        2) `SQLALCHEMY_DATABASE_URI`
        3) alembic.ini -> sqlalchemy.url

    Returns:
        str: Database connection URL.

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


# Alembic’s target metadata used for autogenerate (naming conv. lives on metadata).
target_metadata = BaseMetadata


# -----------------------------------------------------------------------------
# Offline migrations
# -----------------------------------------------------------------------------
def run_migrations_offline() -> None:
    """Run migrations in 'offline' mode.

    This configures the context with the URL only (no engine/DBAPI). The output
    is a SQL script suitable for code review and deterministic deployments.
    """
    url = _get_db_url()
    x = _xargs()
    if x.get("show_url") == "1" or os.getenv("ALEMBIC_SHOW_URL") == "1":
        logger.info("Using DATABASE_URL (masked): %s", _mask_url(url))

    context.configure(
        url=url,
        target_metadata=target_metadata,
        literal_binds=True,  # embed values in the generated SQL
        dialect_opts={"paramstyle": "named"},
        compare_type=True,  # detect column type changes
        compare_server_default=True,
        include_schemas=True,
        version_table_schema=target_metadata.schema,  # respect schema naming conventions
    )

    with context.begin_transaction():
        context.run_migrations()


# -----------------------------------------------------------------------------
# Online migrations (async engine)
# -----------------------------------------------------------------------------
def _online_engine_kwargs(url: str) -> dict[str, Any]:
    """Return keyword arguments for creating an async engine.

    Args:
        url: Database URL.

    Returns:
        Dict[str, Any]: Engine creation kwargs.
    """
    echo_sql = (os.getenv("ECHO_SQL") == "1") or (config.get_main_option("echo_sql") == "true")
    return {
        "echo": echo_sql,
        "poolclass": pool.NullPool,  # migrations shouldn't maintain pooled connections
    }


async def _run_migrations_async() -> None:
    """Run migrations in 'online' mode using an async engine."""
    url = _get_db_url()
    x = _xargs()
    if x.get("show_url") == "1" or os.getenv("ALEMBIC_SHOW_URL") == "1":
        logger.info("Using DATABASE_URL (masked): %s", _mask_url(url))

    connectable: AsyncEngine = create_async_engine(url, **_online_engine_kwargs(url))

    async with connectable.connect() as connection:
        await connection.run_sync(_configure_and_run)

    await connectable.dispose()


def _configure_and_run(connection: Connection) -> None:
    """Configure Alembic context with a live connection and run migrations.

    Args:
        connection: Synchronous connection provided by `AsyncConnection.run_sync`.
    """
    context.configure(
        connection=connection,
        target_metadata=target_metadata,
        compare_type=True,
        compare_server_default=True,
        include_schemas=True,
        version_table_schema=target_metadata.schema,
    )

    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online() -> None:
    """Entry point used by Alembic for online migrations (async safe)."""
    import asyncio

    asyncio.run(_run_migrations_async())


# -----------------------------------------------------------------------------
# Entrypoint
# -----------------------------------------------------------------------------
if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
