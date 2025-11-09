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
from typing import Any, Protocol, cast, runtime_checkable
from urllib.parse import urlparse, urlunparse

import redis.asyncio as aioredis

from stacklion_api.config.settings import Settings, get_settings

__all__ = [
    "RedisClient",
    "init_redis",
    "close_redis",
    "get_redis_client",
    "redis_dependency",
]


@runtime_checkable
class RedisClient(Protocol):
    """Minimal async Redis protocol used by Stacklion.

    Intentionally small to remain stable across `types-redis` stub changes.
    Add new methods here only when a caller needs them.
    """

    # Health / lifecycle
    async def ping(self) -> Any: ...
    async def close(self) -> None: ...

    # Common operations used by infra caches
    async def get(self, key: str) -> Any: ...
    async def set(
        self,
        key: str,
        value: Any,
        *,
        ex: int | None = None,  # seconds (common pattern)
        px: int | None = None,  # milliseconds (optional)
        nx: bool | None = None,
        xx: bool | None = None,
    ) -> Any: ...
    async def exists(self, *keys: str) -> Any: ...
    async def expire(self, key: str, seconds: int) -> Any: ...


# Single shared client
_client: RedisClient | None = None

# Developer-friendly default URL (fixes local tests)
_DEFAULT_REDIS_URL = "redis://localhost:6379/0"


def _maybe_swap_hostname(url: str) -> str:
    """Swap docker-compose host 'redis' to 'localhost' outside CI.

    Args:
        url: A redis URL like 'redis://user:pass@redis:6379/0'.

    Returns:
        The same URL, but with hostname rewritten to 'localhost' when not running in CI
        and the original host is exactly 'redis'.
    """
    try:
        parsed = urlparse(url)
        if parsed.hostname == "redis" and not os.getenv("CI"):
            host = "localhost"
            port = parsed.port or 6379
            if parsed.username and parsed.password:
                netloc = f"{parsed.username}:{parsed.password}@{host}:{port}"
            else:
                netloc = f"{host}:{port}"
            return urlunparse((parsed.scheme, netloc, parsed.path or "/0", "", "", ""))
    except Exception as exc:  # pragma: no cover (non-critical debug path)
        logging.getLogger(__name__).debug(
            "redis url parse failed; keeping original url: %s", url, exc_info=exc
        )
    return url


def init_redis(settings: Settings) -> None:
    """Initialize the global async Redis client.

    Idempotent: subsequent calls are no-ops.

    Args:
        settings: Application settings providing `redis_url`.
    """
    global _client

    if _client is not None:
        return

    # Use localhost fallback instead of raising when not configured.
    url = str(settings.redis_url or _DEFAULT_REDIS_URL)
    url = _maybe_swap_hostname(url)

    # `from_url` is untyped in stubs; cast to our protocol type.
    _client = cast(
        RedisClient,
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
        with suppress(RuntimeError):
            await _client.close()
        _client = None


def get_redis_client() -> RedisClient:
    """Return the initialized Redis client.

    Returns:
        RedisClient: The global Redis client.

    Raises:
        RuntimeError: If initialization failed unexpectedly.
    """
    global _client
    if _client is None:
        init_redis(get_settings())
    if _client is None:
        raise RuntimeError("Redis client not initialized (init_redis failed)")
    return _client


@asynccontextmanager
async def redis_dependency() -> AsyncGenerator[RedisClient, None]:
    """Yield the shared Redis client for DI."""
    yield get_redis_client()
