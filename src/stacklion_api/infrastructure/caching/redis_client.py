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
"""

from __future__ import annotations

from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager, suppress
from typing import TYPE_CHECKING

import redis.asyncio as aioredis

from stacklion_api.config.settings import Settings, get_settings

# mypy sees Redis[str] (decode_responses=True -> str); runtime sees plain Redis (non-generic)
if TYPE_CHECKING:
    from redis.asyncio import Redis as _Redis

    type RedisT = _Redis[str]
else:
    from redis.asyncio import Redis as RedisT  # type: ignore[assignment]

_client: RedisT | None = None


def init_redis(settings: Settings) -> None:
    """Initialize the global async Redis client.

    Args:
        settings: Application settings providing `redis_url`.

    Raises:
        ValueError: If `redis_url` is empty.
    """
    global _client

    if not settings.redis_url:
        raise ValueError("redis_url must be configured")
    if _client is not None:
        # Already initialized (idempotent).
        return

    _client = aioredis.from_url(
        url=settings.redis_url,
        encoding="utf-8",
        decode_responses=True,
        health_check_interval=15,
        socket_timeout=3.0,
        socket_connect_timeout=3.0,
    )


async def close_redis() -> None:
    """Close the global Redis client at shutdown."""
    global _client
    if _client is not None:
        # In some TestClient lifecycles, the loop may be closed by the time we shut down.
        with suppress(RuntimeError):
            await _client.close()
        _client = None


def get_redis_client() -> RedisT:
    """Return the initialized Redis client.

    Returns:
        RedisT: The global Redis client.
    """
    global _client
    if _client is None:
        init_redis(get_settings())
    if _client is None:
        # Defensive after lazy init attempt.
        raise RuntimeError("Redis client not initialized (init_redis failed)")
    return _client


@asynccontextmanager
async def redis_dependency() -> AsyncGenerator[RedisT, None]:
    """Yield the shared Redis client for DI."""
    yield get_redis_client()
