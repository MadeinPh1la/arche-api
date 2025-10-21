# Copyright (c) Stacklion.
# SPDX-License-Identifier: MIT
"""Async SQLAlchemy engine/session factory and DI dependency.

This module owns the application-global async SQLAlchemy engine and
`async_sessionmaker`, plus a FastAPI-friendly dependency that yields an
`AsyncSession`.

Lifecycle:
    * Call `init_engine_and_sessionmaker(settings)` at app startup (lifespan).
    * Use `get_db_session()` as a dependency in request handlers or services.
    * Call `dispose_engine()` during shutdown.

Notes:
    * No business logic here; repositories/services consume the session.
    * `pool_pre_ping=True` helps surface dead connections before use.
    * In test transports that may skip lifespan, `get_db_session()` lazily
      initializes the engine/sessionmaker via `get_settings()`.
"""

from __future__ import annotations

from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager, suppress

from sqlalchemy.exc import IllegalStateChangeError, InvalidRequestError
from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)

from stacklion_api.config.settings import Settings, get_settings

_engine: AsyncEngine | None = None
_sessionmaker: async_sessionmaker[AsyncSession] | None = None


def init_engine_and_sessionmaker(settings: Settings) -> None:
    """Initialize the global async engine and sessionmaker.

    Args:
        settings: Application settings providing `database_url`.

    Raises:
        ValueError: If `database_url` is empty.
    """
    global _engine, _sessionmaker

    if not settings.database_url:
        raise ValueError("database_url must be configured")
    if _engine is not None:
        # Already initialized (idempotent).
        return

    _engine = create_async_engine(
        url=settings.database_url,
        future=True,
        pool_pre_ping=True,
        echo=False,
    )
    _sessionmaker = async_sessionmaker(bind=_engine, expire_on_commit=False, class_=AsyncSession)


async def dispose_engine() -> None:
    """Dispose the global engine at application shutdown."""
    global _engine
    if _engine is not None:
        await _engine.dispose()
        _engine = None


def get_sessionmaker() -> async_sessionmaker[AsyncSession]:
    """Return the initialized async sessionmaker.

    Returns:
        async_sessionmaker[AsyncSession]: The global session factory.

    Raises:
        RuntimeError: If the sessionmaker is not yet initialized.
    """
    if _sessionmaker is None:
        raise RuntimeError("DB sessionmaker not initialized (call init_engine_and_sessionmaker)")
    return _sessionmaker


@asynccontextmanager
async def get_db_session() -> AsyncGenerator[AsyncSession, None]:
    """Yield a new `AsyncSession` for DI.

    Yields:
        AsyncSession: A non-expiring SQLAlchemy async session.

    Notes:
        * Rolls back any open transaction (if present) and closes the session on exit.
        * Lifespan-less test transports are supported via lazy init.
    """
    # Ensure one-time init if lifespan didn't run.
    if _sessionmaker is None:
        init_engine_and_sessionmaker(get_settings())

    session = get_sessionmaker()()
    try:
        yield session
    finally:
        # Only rollback if an active transaction exists; tolerate provisioning state.
        try:
            tx = session.get_transaction()
            if tx and tx.is_active:
                await session.rollback()
        except InvalidRequestError:
            # Occurs when the session was still provisioning a connection.
            pass

        # Close defensively; tolerate provisioning/illegal-state transitions in tests.
        with suppress(InvalidRequestError, IllegalStateChangeError):
            await session.close()
