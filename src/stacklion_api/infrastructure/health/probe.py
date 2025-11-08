# Copyright (c) Stacklion.
# SPDX-License-Identifier: MIT
"""Readiness probes for Postgres & Redis (with Prometheus histograms).

Summary:
    Provides fast, safe readiness checks for Postgres and Redis and records
    their latencies to Prometheus histograms. Collectors are obtained lazily
    from the centralized observability module to avoid duplicate registration.

Design:
    * Always observe latency, whether probe succeeds or fails.
    * Small public surface: `DbRedisProbe.db()` and `.redis()` returning
      `(success: bool, detail: str | None)`.

Dependencies:
    - SQLAlchemy AsyncSession/async_sessionmaker for DB checks
    - redis.asyncio.Redis for Redis checks
"""

from __future__ import annotations

import time
from typing import Any

from prometheus_client import Histogram
from redis.asyncio import Redis
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from stacklion_api.infrastructure.observability.metrics import (
    get_readyz_db_latency_seconds,
    get_readyz_redis_latency_seconds,
)

__all__ = ["DbRedisProbe"]


class DbRedisProbe:
    """Readiness probe for Postgres and Redis."""

    def __init__(
        self,
        session_factory: async_sessionmaker[AsyncSession],
        redis: Redis[Any],
    ) -> None:
        """Initialize the probe.

        Args:
            session_factory: Async SQLAlchemy session factory bound to the DB.
            redis: Async Redis client instance for connectivity checks.
        """
        self._session_factory = session_factory
        self._redis: Redis[Any] = redis
        # Bind histograms once (lazy/idempotent underneath)
        self._db_hist: Histogram = get_readyz_db_latency_seconds()
        self._redis_hist: Histogram = get_readyz_redis_latency_seconds()

    async def db(self) -> tuple[bool, str | None]:
        """Probe Postgres using a trivial `SELECT 1`.

        Returns:
            tuple[bool, str | None]: (success, diagnostic detail or None)
        """
        start = time.perf_counter()
        ok = True
        detail: str | None = None
        try:
            async with self._session_factory() as session:
                await session.execute(text("SELECT 1"))
        except Exception as exc:  # exercised in integration tests
            ok = False
            detail = str(exc)
        finally:
            self._db_hist.observe(time.perf_counter() - start)
        return ok, detail

    async def redis(self) -> tuple[bool, str | None]:
        """Probe Redis using `PING`.

        Returns:
            tuple[bool, str | None]: (success, diagnostic detail or None)
        """
        start = time.perf_counter()
        ok = True
        detail: str | None = None
        try:
            pong = await self._redis.ping()
            ok = bool(pong)
            if not ok:
                detail = "unexpected PONG value"
        except Exception as exc:  # exercised in integration tests
            ok = False
            detail = str(exc)
        finally:
            self._redis_hist.observe(time.perf_counter() - start)
        return ok, detail
