# Copyright (c) Arche.
# SPDX-License-Identifier: MIT
"""FastAPI dependency wiring for health probes.

Provides a DI factory that yields a `DbRedisProbe` bound to the app's
AsyncSession factory and the shared Redis client. This module contains no
probe logic—only wiring—so the implementation remains in infra.
"""

from __future__ import annotations

from typing import Annotated

from fastapi import Depends
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from arche_api.infrastructure.caching.redis_client import (
    RedisClient as RedisProto,
)
from arche_api.infrastructure.caching.redis_client import (
    get_redis_client,
)
from arche_api.infrastructure.db.session import get_session_factory
from arche_api.infrastructure.health.probe import DbRedisProbe


def _build_probe(
    session_factory: async_sessionmaker[AsyncSession],
    redis: RedisProto,
) -> DbRedisProbe:
    """Construct the concrete probe (kept separate for easy test injection)."""
    return DbRedisProbe(session_factory=session_factory, redis=redis)


async def probe_dependency(
    session_factory: Annotated[async_sessionmaker[AsyncSession], Depends(get_session_factory)],
) -> DbRedisProbe:
    """FastAPI dependency that provides a ready-to-use `DbRedisProbe` instance."""
    redis = get_redis_client()
    return _build_probe(session_factory, redis)
