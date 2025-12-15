# src/arche_api/dependencies/core/bootstrap.py
# Copyright (c)
# SPDX-License-Identifier: MIT
"""Core bootstrap for infrastructure (DB, Redis, HTTP, tracing).

This module owns the lifecycle of shared infrastructure used by the FastAPI app.
It is intentionally thin: configuration is read from Settings, and all heavy
lifting is delegated to the infrastructure modules.

The single public surface is :func:`bootstrap`, an async context manager that
yields a simple state object with the resolved Settings and shared HTTP client.
"""

from __future__ import annotations

from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager
from dataclasses import dataclass

import httpx
from fastapi import FastAPI

from arche_api.config.settings import Settings, get_settings
from arche_api.infrastructure.logging.logger import get_json_logger

logger = get_json_logger(__name__)


@dataclass
class BootstrapState:
    """State yielded by the bootstrap context manager."""

    settings: Settings
    http_client: httpx.AsyncClient


@asynccontextmanager
async def bootstrap(app: FastAPI) -> AsyncGenerator[BootstrapState, None]:
    """Initialize and teardown shared infrastructure.

    Responsibilities:
        * Load application settings.
        * Initialize DB engine/sessionmaker.
        * Initialize Redis client.
        * Create a shared HTTPX AsyncClient.
        * Ensure all of the above are shut down on exit, even on error.

    Args:
        app: FastAPI application instance (unused today, reserved for future hooks).

    Yields:
        BootstrapState: Resolved settings and shared HTTP client.
    """
    settings: Settings = get_settings()
    logger.info("bootstrap.start")

    # Import infrastructure modules here so tests can monkeypatch their functions.
    import arche_api.infrastructure.caching.redis_client as redis_client
    import arche_api.infrastructure.database.session as db_session

    # Initialize infrastructure. Tests monkeypatch these to avoid touching real infra.
    db_session.init_engine_and_sessionmaker(settings)
    redis_client.init_redis(settings)

    http_client = httpx.AsyncClient()

    state = BootstrapState(settings=settings, http_client=http_client)

    try:
        yield state
    finally:
        # Close HTTP client
        try:
            await http_client.aclose()
        except Exception:
            logger.exception("bootstrap.http_client_close_failed")

        # Close Redis (tests patch redis_client.close_redis)
        try:
            await redis_client.close_redis()
        except Exception:
            logger.exception("bootstrap.redis_close_failed")

        # Dispose DB engine (tests patch db_session.dispose_engine)
        try:
            await db_session.dispose_engine()
        except Exception:
            logger.exception("bootstrap.db_dispose_failed")

        logger.info("bootstrap.stop")
