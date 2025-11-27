# src/stacklion_api/infrastructure/caching/json_cache.py
# Copyright (c)
# SPDX-License-Identifier: MIT
"""JSON Cache (Redis-backed).

Synopsis:
    Thin adapter that implements the application CachePort Protocol on top of
    the shared Redis client provided by `infrastructure/caching/redis_client.py`.
    Provides namespaced JSON get/set with TTL and an optional single-flight
    helper for hot keys.

Design:
    * Uses the global Redis client via `get_redis_client()`.
    * Pure JSON (utf-8) serialization; no pickle.
    * Key policy:
        - Namespace prefix owns the Stacklion + vertical + version:
            `stacklion:market_data:v1`
        - Callers provide the remaining resource-specific segments:
            e.g. `historical:AAPL,MSFT:1day:...` or `quote:AAPL`
    * Single-flight helper for hot keys with short-lived locks.

Layer:
    infrastructure/caching

See Also:
    - stacklion_api.infrastructure.caching.redis_client
    - stacklion_api.application.interfaces.cache_port.CachePort
"""

from __future__ import annotations

import asyncio
import json
import time
from collections.abc import Awaitable, Callable, Mapping
from contextlib import suppress
from typing import Any

from stacklion_api.application.interfaces.cache_port import CachePort
from stacklion_api.infrastructure.caching.redis_client import get_redis_client
from stacklion_api.infrastructure.observability.metrics import (
    get_cache_operation_duration_seconds,
    get_cache_operations_total,
)

__all__ = [
    "RedisJsonCache",
    "TTL_QUOTE_HOT_S",
    "TTL_INTRADAY_RECENT_S",
    "TTL_EOD_S",
    "TTL_REFERENCE_S",
    "read_through_json",
]

# -----------------------------------------------------------------------------
# TTL bands (seconds)
# -----------------------------------------------------------------------------

#: Very hot latest quotes (small, fast-moving).
TTL_QUOTE_HOT_S = 5

#: Recent intraday windows (e.g. last 1–2 days).
TTL_INTRADAY_RECENT_S = 30

#: End-of-day / older historical bars.
TTL_EOD_S = 300

#: Reference / metadata configuration.
TTL_REFERENCE_S = 3600


async def read_through_json(
    cache: CachePort,
    key: str,
    *,
    ttl: int,
    loader: Callable[[], Awaitable[Mapping[str, Any] | None]],
) -> Mapping[str, Any] | None:
    """Generic read-through helper without single-flight.

    Args:
        cache: CachePort implementation.
        key: Fully-qualified cache key (including any namespace prefix).
        ttl: Time-to-live for new entries.
        loader: Async callable that fetches the value on a cache miss.

    Returns:
        The mapping returned from cache or loader, or ``None`` if loader
        returns ``None``.
    """
    cached = await cache.get_json(key)
    if cached is not None:
        return cached

    value = await loader()
    if value is not None and ttl > 0:
        await cache.set_json(key, value, ttl=ttl)
    return value


class RedisJsonCache(CachePort):
    """Redis-backed implementation of the CachePort Protocol.

    This implementation assumes keys are built as:

        stacklion:{vertical}:v1:{resource}:{shape}

    The namespace parameter configures the stacklion + vertical + version
    prefix; the `key` arguments passed to methods are the remaining segments.
    """

    def __init__(self, *, namespace: str = "stacklion:market_data:v1") -> None:
        """Initialize the cache adapter.

        Args:
            namespace: Prefix applied to all keys to avoid collisions.
        """
        self._ns = namespace

    # ------------------------------------------------------------------ #
    # Internal key builder
    # ------------------------------------------------------------------ #
    def _k(self, key: str) -> str:
        """Build a namespaced key.

        Args:
            key: Unqualified cache key (resource-specific tail).

        Returns:
            Fully namespaced cache key.
        """
        key = key.lstrip(":")
        return f"{self._ns}:{key}"

    def make_key(self, *segments: str) -> str:
        """Build a resource tail key from simple segments.

        This does **not** apply the namespace; it only constructs the tail
        passed into `get_json`/`set_json`.

        Args:
            *segments: Key segments to join with ":".

        Returns:
            Tail key suitable to pass as ``key``.
        """
        return ":".join(str(seg).strip(":") for seg in segments if seg != "")

    # ------------------------------------------------------------------ #
    # CachePort implementation
    # ------------------------------------------------------------------ #
    async def get_json(self, key: str) -> Mapping[str, Any] | None:
        """Get a JSON-serialized value by key.

        Args:
            key: Unqualified cache key.

        Returns:
            Deserialized mapping if present, else None.
        """
        hist = get_cache_operation_duration_seconds()
        counter = get_cache_operations_total()
        start = time.perf_counter()
        hit_label = "false"

        try:
            redis = get_redis_client()
            raw = await redis.get(self._k(key))
            if raw is None:
                return None
            hit_label = "true"
            return json.loads(raw)
        finally:
            duration = time.perf_counter() - start
            with suppress(Exception):
                hist.labels(
                    operation="get_json",
                    namespace=self._ns,
                    hit=hit_label,
                ).observe(duration)
                counter.labels(
                    operation="get_json",
                    namespace=self._ns,
                    hit=hit_label,
                ).inc()

    async def set_json(self, key: str, value: Mapping[str, Any], *, ttl: int) -> None:
        """Set a JSON-serialized value with TTL.

        Args:
            key: Unqualified cache key.
            value: JSON-serializable mapping.
            ttl: Time-to-live in seconds.
        """
        hist = get_cache_operation_duration_seconds()
        counter = get_cache_operations_total()
        start = time.perf_counter()

        try:
            if ttl <= 0:
                return

            redis = get_redis_client()
            await redis.set(self._k(key), json.dumps(value), ex=ttl)
        finally:
            duration = time.perf_counter() - start
            with suppress(Exception):
                hist.labels(
                    operation="set_json",
                    namespace=self._ns,
                    hit="n/a",
                ).observe(duration)
                counter.labels(
                    operation="set_json",
                    namespace=self._ns,
                    hit="n/a",
                ).inc()

    # ------------------------------------------------------------------ #
    # Single-flight / stampede protection
    # ------------------------------------------------------------------ #
    async def get_or_set_json_singleflight(
        self,
        key: str,
        *,
        ttl: int,
        loader: Callable[[], Awaitable[Mapping[str, Any] | None]],
        lock_ttl: int = 5,
        wait_timeout: float = 0.25,
        wait_interval: float = 0.01,
    ) -> Mapping[str, Any] | None:
        """Read-through caching with best-effort stampede protection.

        Strategy:
            1. Check cache; return on hit.
            2. Try to acquire a short-lived lock via SET NX.
            3. If lock acquired:
                * Call loader, set cache, let lock expire naturally.
            4. If lock not acquired:
                * Briefly spin, re-checking cache.
                * If still empty, fall back to loader without lock.

        Lock keys are derived as ``{data_key}:lock`` and rely on TTL expiry
        instead of explicit delete to keep the RedisClient protocol minimal.

        Args:
            key: Unqualified cache key (tail segment).
            ttl: Time-to-live for cache entries.
            loader: Async callable used to fetch the value on a miss.
            lock_ttl: TTL for the lock key in seconds.
            wait_timeout: Max seconds to wait for another worker to fill cache.
            wait_interval: Sleep between polls in seconds.

        Returns:
            Mapping from cache or loader, or ``None`` if loader returns None.
        """
        # Fast path: try cache first.
        cached = await self.get_json(key)
        if cached is not None:
            return cached

        redis = get_redis_client()
        data_key = self._k(key)
        lock_key = f"{data_key}:lock"

        # Try to acquire a lock.
        got_lock = False
        try:
            res = await redis.set(lock_key, "1", nx=True, ex=lock_ttl)
            got_lock = bool(res)
        except Exception:  # pragma: no cover - defensive
            got_lock = False

        if got_lock:
            # We won the lock: re-check cache in case someone raced us.
            cached = await self.get_json(key)
            if cached is not None:
                return cached

            value = await loader()
            if value is not None and ttl > 0:
                await self.set_json(key, value, ttl=ttl)
            # Let the lock expire naturally.
            return value

        # Someone else has the lock: briefly wait for them to fill cache.
        deadline = time.perf_counter() + wait_timeout
        while time.perf_counter() < deadline:
            cached = await self.get_json(key)
            if cached is not None:
                return cached
            await asyncio.sleep(wait_interval)

        # Fallback: loader without single-flight if cache is still empty.
        value = await loader()
        if value is not None and ttl > 0:
            await self.set_json(key, value, ttl=ttl)
        return value
