# Copyright (c) Stacklion.
# SPDX-License-Identifier: MIT
"""JSON Cache (Redis-backed).

Synopsis:
    Thin adapter that implements the application CachePort Protocol on top of
    the shared Redis client provided by `infrastructure/caching/redis_client.py`.
    Provides namespaced JSON get/set with TTL, without owning a connection.

Design:
    * Uses the global Redis client via `get_redis_client()`.
    * Pure JSON (utf-8) serialization; no pickle.
    * No key policy here beyond namespacing; higher layers decide keys.

Layer:
    infrastructure/caching

See also:
    - stacklion_api.infrastructure.caching.redis_client
    - stacklion_api.application.interfaces.cache_port.CachePort
"""

from __future__ import annotations

import json
from collections.abc import Mapping
from typing import Any

from stacklion_api.application.interfaces.cache_port import CachePort
from stacklion_api.infrastructure.caching.redis_client import get_redis_client


class RedisJsonCache(CachePort):
    """Redis-backed implementation of the CachePort Protocol."""

    def __init__(self, *, namespace: str = "md:v1") -> None:
        """Initialize the cache adapter.

        Args:
            namespace: Prefix applied to all keys to avoid collisions.
        """
        self._ns = namespace

    def _k(self, key: str) -> str:
        """Build a namespaced key.

        Args:
            key: Unqualified cache key.

        Returns:
            Fully namespaced cache key.
        """
        return f"{self._ns}:{key}"

    async def get_json(self, key: str) -> Mapping[str, Any] | None:
        """Get a JSON-serialized value by key.

        Args:
            key: Unqualified cache key.

        Returns:
            Deserialized mapping if present, else None.
        """
        redis = get_redis_client()
        raw = await redis.get(self._k(key))
        return json.loads(raw) if raw else None

    async def set_json(self, key: str, value: Mapping[str, Any], ttl: int) -> None:
        """Set a JSON-serialized value with TTL.

        Args:
            key: Unqualified cache key.
            value: JSON-serializable mapping.
            ttl: Time-to-live in seconds.
        """
        redis = get_redis_client()
        await redis.set(self._k(key), json.dumps(value), ex=ttl)
