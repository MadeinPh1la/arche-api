# Copyright (c) Stacklion.
# SPDX-License-Identifier: MIT
"""Dependency override for the health router's probe.

Provides a concrete probe with real Postgres + Redis checks and emits latency
metrics via Prometheus histograms, matching the router's expected contract.
"""

from __future__ import annotations

import time
from typing import TYPE_CHECKING, Protocol

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from stacklion_api.infrastructure.observability.metrics import (
    get_readyz_db_latency_seconds,
    get_readyz_redis_latency_seconds,
)

# Typing-only Redis alias: generic for mypy, non-generic at runtime.
if TYPE_CHECKING:
    from redis.asyncio import Redis as _Redis

    type RedisT = _Redis[str]
else:
    from redis.asyncio import Redis as RedisT  # type: ignore[assignment]


class _RouterHealthProbeContract(Protocol):
    """Contract expected by `health_router` (returns (ok, detail))."""

    async def db(self) -> tuple[bool, str | None]: ...
    async def redis(self) -> tuple[bool, str | None]: ...


class PostgresRedisProbe(_RouterHealthProbeContract):
    """Concrete health probe that checks Postgres and Redis."""

    def __init__(self, session: AsyncSession, redis: RedisT) -> None:
        self._session = session
        self._redis = redis

    async def db(self) -> tuple[bool, str | None]:
        """Return (ok, detail) for a trivial Postgres round-trip."""
        t0 = time.perf_counter()
        ok = False
        detail: str | None = None
        try:
            await self._session.execute(text("SELECT 1"))
            ok = True
        except Exception as exc:  # noqa: BLE001
            detail = str(exc)
        finally:
            get_readyz_db_latency_seconds().observe(time.perf_counter() - t0)

        return ok, detail

    async def redis(self) -> tuple[bool, str | None]:
        """Return (ok, detail) for a Redis PING."""
        t0 = time.perf_counter()
        ok = False
        detail: str | None = None
        try:
            ok = bool(await self._redis.ping())
        except Exception as exc:  # noqa: BLE001
            detail = str(exc)
        finally:
            get_readyz_redis_latency_seconds().observe(time.perf_counter() - t0)

        return ok, detail
