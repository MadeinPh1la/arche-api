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
from typing import TYPE_CHECKING, Any, Protocol, cast, runtime_checkable
from urllib.parse import urlparse, urlunparse

import redis.asyncio as aioredis

# Provide a *typed* alias for the concrete Redis client that satisfies environments
# where stubs make redis.asyncio.client.Redis a generic (e.g., Redis[str]).
if TYPE_CHECKING:
    from redis.asyncio.client import Redis as _RedisGeneric
    AioredisRedis = _RedisGeneric[str]
else:
    # At runtime, avoid subscripted generics; import the concrete class directly.
    from redis.asyncio.client import Redis as AioredisRedis  # type: ignore[assignment]

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

    Intentionally small to remain stable across redis/typing changes.
    Extend only when a caller truly needs a new method.
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
        ex: int | None = None,  # seconds
        px: int | None = None,  # milliseconds
        nx: bool | None = None,
        xx: bool | None = None,
    ) -> Any: ...
    async def exists(self, *keys: str) -> Any: ...
    async def expire(self, key: str, seconds: int) -> Any: ...


# Single shared client (project-wide)
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


def _create_aioredis_client(url: str) -> AioredisRedis:
    """Build the concrete asyncio Redis client from URL.

    Isolates the construction to keep the rest of the module fully typed.
    """
    client = aioredis.from_url(
        url=url,
        encoding="utf-8",
        decode_responses=True,
        health_check_interval=15,
        socket_timeout=3.0,
        socket_connect_timeout=3.0,
    )
    # Cast once at the boundary; upstream typing varies by redis-py/stubs version.
    return cast(AioredisRedis, client)


def init_redis(settings: Settings) -> None:
    """Initialize the global async Redis client (idempotent).

    Args:
        settings: Application settings providing `redis_url`.
    """
    global _client
    if _client is not None:
        return

    url = str(settings.redis_url or _DEFAULT_REDIS_URL)
    url = _maybe_swap_hostname(url)

    _client = cast(RedisClient, _create_aioredis_client(url))


async def close_redis() -> None:
    """Close the global Redis client at shutdown."""
    global _client
    if _client is not None:
        with suppress(RuntimeError):
            await _client.close()
        _client = None


def get_redis_client() -> RedisClient:
    """Return the initialized Redis client (lazy-inits in tests)."""
    global _client
    if _client is None:
        init_redis(get_settings())
    if _client is None:
        raise RuntimeError("Redis client not initialized (init_redis failed)")
    return _client


from contextlib import asynccontextmanager


@asynccontextmanager
async def redis_dependency() -> AsyncGenerator[RedisClient, None]:
    """Yield the shared Redis client for DI."""
    yield get_redis_client()
