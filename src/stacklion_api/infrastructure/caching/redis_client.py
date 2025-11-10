# src/stacklion_api/infrastructure/caching/redis_client.py
# Copyright (c) Stacklion.
# SPDX-License-Identifier: MIT
"""Async Redis client factory and DI dependency."""

from __future__ import annotations

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
    """Minimal async Redis protocol used by Stacklion."""

    async def ping(self) -> Any: ...
    async def close(self) -> None: ...

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


_client: RedisClient | None = None
_DEFAULT_REDIS_URL = "redis://localhost:6379/0"


def _maybe_swap_hostname(url: str) -> str:
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


def _create_aioredis_client(url: str) -> AioredisRedis:
    """Build the concrete asyncio Redis client from URL."""
    # Make the vendor call through an untyped shim so mypy won't care whether
    # redis stubs define a typed or untyped `from_url` in the current env.
    _from_url: Any = aioredis.from_url
    client = _from_url(
        url=url,
        encoding="utf-8",
        decode_responses=True,
        health_check_interval=15,
        socket_timeout=3.0,
        socket_connect_timeout=3.0,
    )
    return cast(AioredisRedis, client)


def init_redis(settings: Settings) -> None:
    """Initialize the global async Redis client (idempotent)."""
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
            # redis.asyncio clients expose an awaitable `.close()`
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


@asynccontextmanager
async def redis_dependency() -> AsyncGenerator[RedisClient, None]:
    """Yield the shared Redis client for DI."""
    yield get_redis_client()
