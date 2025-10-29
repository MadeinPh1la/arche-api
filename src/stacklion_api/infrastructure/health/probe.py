# src/stacklion_api/infrastructure/health/probe.py
# Copyright (c) Stacklion.
# SPDX-License-Identifier: MIT
"""
Readiness Probes (DB & Redis) with Prometheus Histograms.

Summary:
    Provides lightweight health checks for Postgres and Redis and records their
    latencies to Prometheus histograms. Collectors are created lazily and
    idempotently to avoid duplicate-timeseries errors during pytest collection
    or dev reloads.

Design:
    - Lazily create histograms via singleton getters (`readyz_db_latency`,
      `readyz_redis_latency`) that reuse existing collectors in the default
      registry when present.
    - Probes are fast, safe (catch-all error handling), and always observable:
      latency is recorded whether the probe succeeds or fails.
    - Public API is intentionally small: `DbRedisProbe.db()` and
      `DbRedisProbe.redis()` each return `(success: bool, detail: str | None)`.

Usage:
    probe = DbRedisProbe(session_factory, redis_client)
    ok_db, detail_db = await probe.db()
    ok_redis, detail_redis = await probe.redis()
"""

from __future__ import annotations

import time
from threading import Lock

from prometheus_client import REGISTRY, Histogram
from redis.asyncio import Redis
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

__all__ = ["DbRedisProbe", "readyz_db_latency", "readyz_redis_latency"]

# ------------------------------------------------------------------------------
# Lazy, idempotent Prometheus collectors
# ------------------------------------------------------------------------------

_DB_HIST: Histogram | None = None
_DB_LOCK = Lock()

_REDIS_HIST: Histogram | None = None
_REDIS_LOCK = Lock()


def readyz_db_latency() -> Histogram:
    """Return the singleton Histogram for DB readiness latency.

    The collector is created lazily and reuses any existing collector with the
    same name in the default registry to avoid duplicate-timeseries errors.

    Returns:
        A `Histogram` bound to the default CollectorRegistry.
    """
    global _DB_HIST
    if _DB_HIST is not None:
        return _DB_HIST
    with _DB_LOCK:
        if _DB_HIST is not None:
            return _DB_HIST
        name = "readyz_db_latency_seconds"
        try:
            _DB_HIST = Histogram(
                name,
                "Latency of Postgres readiness probe (seconds).",
                buckets=(0.01, 0.025, 0.05, 0.1, 0.25, 0.5, 1.0, 2.5, 5.0, float("inf")),
            )
        except ValueError:
            # Already registered — reuse existing collector from the default registry.
            existing = REGISTRY._names_to_collectors.get(name)  # private attr in lib
            if isinstance(existing, Histogram):
                _DB_HIST = existing
            else:  # defensive branch
                raise
        return _DB_HIST


def readyz_redis_latency() -> Histogram:
    """Return the singleton Histogram for Redis readiness latency.

    The collector is created lazily and reuses any existing collector with the
    same name in the default registry to avoid duplicate-timeseries errors.

    Returns:
        A `Histogram` bound to the default CollectorRegistry.
    """
    global _REDIS_HIST
    if _REDIS_HIST is not None:
        return _REDIS_HIST
    with _REDIS_LOCK:
        if _REDIS_HIST is not None:
            return _REDIS_HIST
        name = "readyz_redis_latency_seconds"
        try:
            _REDIS_HIST = Histogram(
                name,
                "Latency of Redis readiness probe (seconds).",
                buckets=(0.005, 0.01, 0.025, 0.05, 0.1, 0.25, 0.5, 1.0, float("inf")),
            )
        except ValueError:
            # Already registered — reuse existing collector from the default registry.
            existing = REGISTRY._names_to_collectors.get(name)  # private attr in lib
            if isinstance(existing, Histogram):
                _REDIS_HIST = existing
            else:  # defensive branch
                raise
        return _REDIS_HIST


# ------------------------------------------------------------------------------
# Readiness probe implementation
# ------------------------------------------------------------------------------


class DbRedisProbe:
    """Performs lightweight readiness probes for Postgres and Redis.

    Probes are designed to be:
      * Fast: Trivial operations that avoid heavy work and do not allocate rows.
      * Safe: Catch-all error handling that returns a boolean plus diagnostic text.
      * Observable: Always record latency to Prometheus, regardless of success/failure.

    Args:
        session_factory: Async SQLAlchemy session factory bound to the primary DB.
        redis: Async Redis client instance.
    """

    def __init__(self, session_factory: async_sessionmaker[AsyncSession], redis: Redis) -> None:
        """Initialize the probe with DB session factory and Redis client.

        Args:
            session_factory: Factory for creating async DB sessions.
            redis: Redis client for connectivity checks.
        """
        self._session_factory = session_factory
        self._redis = redis

    async def db(self) -> tuple[bool, str | None]:
        """Probe Postgres by executing a trivial `SELECT 1`.

        Returns:
            A tuple of:
                - success (bool): True if the probe succeeded, False otherwise.
                - detail (str | None): Error string when failed; None on success.

        Notes:
            Latency is always recorded to the `readyz_db_latency_seconds` histogram,
            even when the probe fails.
        """
        start = time.perf_counter()
        ok = True
        detail: str | None = None
        try:
            async with self._session_factory() as session:
                # Use a trivial text query; no row materialization required.
                await session.execute(text("SELECT 1"))
        except Exception as exc:  # failure path exercised in integration tests
            ok = False
            detail = str(exc)
        finally:
            duration = time.perf_counter() - start
            readyz_db_latency().observe(duration)
        return ok, detail

    async def redis(self) -> tuple[bool, str | None]:
        """Probe Redis by issuing a `PING`.

        Returns:
            A tuple of:
                - success (bool): True if a valid PONG was received, False otherwise.
                - detail (str | None): Error string when failed; None on success.

        Notes:
            Latency is always recorded to the `readyz_redis_latency_seconds` histogram,
            even when the probe fails.
        """
        start = time.perf_counter()
        ok = True
        detail: str | None = None
        try:
            pong = await self._redis.ping()
            ok = bool(pong)
            if not ok:
                detail = "unexpected PONG value"
        except Exception as exc:  # failure path exercised in integration tests
            ok = False
            detail = str(exc)
        finally:
            duration = time.perf_counter() - start
            readyz_redis_latency().observe(duration)
        return ok, detail
