# Copyright (c) Stacklion.
# SPDX-License-Identifier: MIT
"""Async Redis client factory and DI dependency.

This module owns a single shared `redis.asyncio.Redis` client instance for the
application, plus a tiny dependency to yield it where needed.

Lifecycle:
    * Call `init_redis(settings)` at app startup (lifespan).
    * Use `redis_dependency()` in routes/services that need Redis.
    * Call `close_redis()` at shutdown.

Notes:
    * Keep keys/namespaces at higher layers; this is infra-only.
    * In test transports that do not execute FastAPI's lifespan, `get_redis_client()`
      lazily initializes the client using `get_settings()` to keep tests robust.
    * If no URL is configured (e.g., local dev), we fall back to localhost.
    * If the configured host is "redis" (docker-compose/CI default) and not in CI,
      we swap to "localhost" to avoid DNS failures on developer machines.
"""

from __future__ import annotations

import logging
import os
from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager, suppress
from typing import cast
from urllib.parse import urlparse, urlunparse

import redis.asyncio as aioredis
from redis.asyncio import Redis

from stacklion_api.config.settings import Settings, get_settings

# Single shared client
_client: Redis | None = None

# Developer-friendly default URL (fixes local tests)
_DEFAULT_REDIS_URL = "redis://localhost:6379/0"


def _maybe_swap_hostname(url: str) -> str:
    """Swap docker-compose host 'redis' to 'localhost' outside CI.

    Args:
        url: A redis URL like 'redis://user:pass@redis:6379/0'.

    Returns:
        str: The same URL, but with hostname rewritten to 'localhost' when
        not running in CI and the original host is exactly 'redis'.
    """
    try:
        parsed = urlparse(url)
        if parsed.hostname == "redis" and not os.getenv("CI"):
            # preserve scheme, port, path, and optional auth
            host = "localhost"
            port = parsed.port or 6379
            if parsed.username and parsed.password:
                netloc = f"{parsed.username}:{parsed.password}@{host}:{port}"
            else:
                netloc = f"{host}:{port}"
            return urlunparse((parsed.scheme, netloc, parsed.path or "/0", "", "", ""))
    except Exception as exc:
        logging.getLogger(__name__).debug(
            "redis url parse failed; keeping original url: %s", url, exc_info=exc
        )
    return url


def init_redis(settings: Settings) -> None:
    """Initialize the global async Redis client.

    Args:
        settings: Application settings providing `redis_url`.
    """
    global _client

    if _client is not None:
        # Already initialized (idempotent).
        return

    # Use localhost fallback instead of raising when not configured.
    url = str(settings.redis_url or _DEFAULT_REDIS_URL)
    url = _maybe_swap_hostname(url)

    # `from_url` is untyped in stubs; cast to satisfy mypy in strict mode.
    _client = cast(
        Redis,
        aioredis.from_url(
            url=url,
            encoding="utf-8",
            decode_responses=True,
            health_check_interval=15,
            socket_timeout=3.0,
            socket_connect_timeout=3.0,
        ),
    )


async def close_redis() -> None:
    """Close the global Redis client at shutdown."""
    global _client
    if _client is not None:
        # In some TestClient lifecycles, the loop may be closed by the time we shut down.
        with suppress(RuntimeError):
            await _client.close()
        _client = None


def get_redis_client() -> Redis:
    """Return the initialized Redis client.

    Returns:
        Redis: The global Redis client.
    """
    global _client
    if _client is None:
        # Lazy init for tests / contexts that didn't run lifespan.
        init_redis(get_settings())
    if _client is None:
        # Defensive after lazy init attempt.
        raise RuntimeError("Redis client not initialized (init_redis failed)")
    return _client


@asynccontextmanager
async def redis_dependency() -> AsyncGenerator[Redis, None]:
    """Yield the shared Redis client for DI."""
    yield get_redis_client()
