# Copyright (c) Stacklion.
# SPDX-License-Identifier: MIT
from __future__ import annotations

from typing import Any

from redis.asyncio import Redis
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker


class DbRedisProbe:
    def __init__(
        self,
        session_factory: async_sessionmaker[AsyncSession],
        redis: Redis[Any],
    ) -> None:
        self._session_factory = session_factory
        self._redis = redis

    async def db(self) -> tuple[bool, str | None]:
        try:
            async with self._session_factory() as session:
                await session.execute(text("SELECT 1"))
            return True, None
        except Exception as exc:
            return False, str(exc)

    async def redis(self) -> tuple[bool, str | None]:
        try:
            pong = await self._redis.ping()
            return bool(pong), None
        except Exception as exc:
            return False, str(exc)
