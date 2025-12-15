# src/arche_api/infrastructure/caching/redis_client.py
# Copyright (c)
# SPDX-License-Identifier: MIT
"""Async Redis client factory and DI dependency.

Design notes:
    * Provides a small Protocol (`RedisClient`) used by adapters.
    * Uses redis.asyncio under the hood for the concrete implementation.
    * Is **loop-aware**: if called from a different event loop than the one
      that created the client, it will transparently create a new client
      bound to the current loop. This avoids cross-loop reuse issues in tests
      (e.g. Starlette TestClient) while remaining effectively singleton for
      long-lived server loops.
    * Test suites may inject a fakeredis client by assigning to the module-level
      `_client`; when that happens we do not overwrite or close it.
"""

from __future__ import annotations

import asyncio
import logging
import os
from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager, suppress
from typing import TYPE_CHECKING, Any, Protocol, cast, runtime_checkable
from urllib.parse import urlparse, urlunparse

import redis.asyncio as aioredis

# -----------------------------------------------------------------------------
# Typed alias for the concrete Redis client.
# Some redis stubs make Redis generic (e.g., Redis[str]).
# Use a proper TypeAlias so mypy recognizes it as a type, not a variable.
# -----------------------------------------------------------------------------
if TYPE_CHECKING:
    from redis.asyncio.client import Redis as _RedisGeneric

    type AioredisRedis = _RedisGeneric[str]
else:
    from redis.asyncio.client import Redis as AioredisRedis  # type: ignore[assignment]

from arche_api.config.settings import Settings, get_settings

__all__ = [
    "RedisClient",
    "init_redis",
    "close_redis",
    "get_redis_client",
    "redis_dependency",
]

logger = logging.getLogger(__name__)


@runtime_checkable
class RedisClient(Protocol):
    """Protocol for the subset of Redis methods used by the application."""

    async def get(self, key: str) -> Any: ...
    async def set(
        self,
        key: str,
        value: Any,
        *,
        ex: int | None = None,
        px: int | None = None,
        nx: bool | None = None,
        xx: bool | None = None,
    ) -> Any: ...
    async def exists(self, *keys: str) -> Any: ...
    async def expire(self, key: str, seconds: int) -> Any: ...
    async def ping(self) -> Any: ...
    async def close(self) -> Any: ...


# Global client + loop identifier. We intentionally track the loop that created
# the client so that we never reuse a redis connection across event loops.
_client: RedisClient | Any | None = None
_client_loop_id: int | None = None

_DEFAULT_REDIS_URL = "redis://localhost:6379/0"


def _current_loop_id() -> int | None:
    """Return the id() of the current running event loop, or None if absent."""
    try:
        loop = asyncio.get_running_loop()
    except RuntimeError:
        return None
    return id(loop)


def _maybe_swap_hostname(url: str) -> str:
    """Swap docker-compose-style hostnames with localhost in dev when needed.

    Args:
        url: Original Redis URL.

    Returns:
        str: Possibly rewritten Redis URL (e.g. redis -> localhost).
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
    except Exception as exc:  # pragma: no cover
        logging.getLogger(__name__).debug(
            "redis url parse failed; keeping original url: %s", url, exc_info=exc
        )
    return url


def _create_aioredis_client(url: str, settings: Settings) -> AioredisRedis:
    """Build the concrete asyncio Redis client from URL and settings.

    Args:
        url: Redis URL.
        settings: Canonical application settings.

    Returns:
        AioredisRedis: Configured Redis client.
    """
    _from_url: Any = aioredis.from_url
    client = _from_url(
        url=url,
        encoding="utf-8",
        decode_responses=True,
        health_check_interval=settings.redis_health_check_interval_s,
        socket_timeout=settings.redis_socket_timeout_s,
        socket_connect_timeout=settings.redis_socket_connect_timeout_s,
    )
    return cast(AioredisRedis, client)


def _is_fake_client(client: Any | None) -> bool:
    """Return True if the given client looks like a fakeredis instance."""
    if client is None:
        return False
    # fakeredis classes live under modules like "fakeredis.aioredis"
    return type(client).__module__.startswith("fakeredis")


def init_redis(settings: Settings) -> None:
    """Initialize the global async Redis client for the **current** event loop.

    This is idempotent *per loop*: calling it again from the same loop is a
    no-op, but calling it from a different loop will create a fresh client
    bound to that loop.

    If tests have injected a fakeredis client into `_client`, this function
    is a no-op and leaves the fake in place.
    """
    global _client, _client_loop_id

    # Respect a test-injected fakeredis client.
    if _is_fake_client(_client):
        return

    loop_id = _current_loop_id()
    if _client is not None and _client_loop_id == loop_id:
        # Same loop, already initialized.
        return

    url = str(settings.redis_url or _DEFAULT_REDIS_URL)
    url = _maybe_swap_hostname(url)

    # Do not attempt to close an existing client from a different event loop;
    # that is exactly what leads to "Event loop is closed" errors in tests.
    _client = cast(RedisClient, _create_aioredis_client(url, settings))
    _client_loop_id = loop_id


async def close_redis() -> None:
    """Close the global Redis client at shutdown (best-effort)."""
    global _client, _client_loop_id

    # Never try to close a fakeredis client; just drop the reference.
    if _client is not None and not _is_fake_client(_client):
        # Only attempt to close if we're on the same loop that created it.
        loop_id = _current_loop_id()
        if _client_loop_id is None or loop_id == _client_loop_id:
            with suppress(RuntimeError, ConnectionError):
                await _client.close()

    _client = None
    _client_loop_id = None


def get_redis_client() -> RedisClient:
    """Return the initialized Redis client (loop-aware, lazy-init in tests).

    In unit tests, a fakeredis instance can be injected via the module-level
    `_client` variable; when present, that instance is returned as-is, and no
    real Redis connection is created.

    Returns:
        RedisClient: Shared Redis client instance.

    Raises:
        RuntimeError: If client could not be initialized.
    """
    global _client, _client_loop_id

    # If tests patched in fakeredis, always return it and never re-init.
    if _is_fake_client(_client):
        return cast(RedisClient, _client)

    loop_id = _current_loop_id()

    if _client is None or (
        _client_loop_id is not None and loop_id is not None and loop_id != _client_loop_id
    ):
        # Either first-time init or we're in a new event loop; (re)initialize.
        init_redis(get_settings())

    if _client is None:
        raise RuntimeError("Redis client not initialized (init_redis failed)")

    return cast(RedisClient, _client)


@asynccontextmanager
async def redis_dependency() -> AsyncGenerator[RedisClient, None]:
    """Yield the shared Redis client for DI.

    Yields:
        RedisClient: Shared client instance.
    """
    yield get_redis_client()
