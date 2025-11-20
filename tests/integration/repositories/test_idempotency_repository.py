# tests/integration/repositories/test_idempotency_repository.py
# Copyright (c) Stacklion.
# SPDX-License-Identifier: MIT
"""
Integration tests for the SQLAlchemy IdempotencyRepository implementation.

These tests operate directly against the database using the IdempotencyKey ORM
model and the concrete repository to verify TTL and result persistence.
"""

from __future__ import annotations

from collections.abc import AsyncGenerator, Mapping
from datetime import datetime, timedelta
from typing import Any

import pytest
from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)

from stacklion_api.adapters.repositories.idempotency_repository import IdempotencyRepository
from stacklion_api.config.settings import get_settings
from stacklion_api.infrastructure.database.models.idempotency import IdempotencyKey


def _utcnow_naive() -> datetime:
    """Return naive UTC, matching TIMESTAMP WITHOUT TIME ZONE columns."""
    return datetime.utcnow()


@pytest.fixture
async def idemp_session() -> AsyncGenerator[AsyncSession, None]:
    """Yield a fresh AsyncSession (and engine) per test.

    Each test gets its own engine and connection pool tied to the same event
    loop, which avoids asyncpg's 'another operation is in progress' and
    cross-loop errors.
    """
    settings = get_settings()
    engine: AsyncEngine = create_async_engine(settings.database_url, future=True)

    # Ensure table exists for this test.
    async with engine.begin() as conn:
        await conn.run_sync(IdempotencyKey.__table__.create, checkfirst=True)

    session_factory = async_sessionmaker(engine, expire_on_commit=False, class_=AsyncSession)

    async with session_factory() as session:
        try:
            yield session
        finally:
            await session.rollback()

    await engine.dispose()


@pytest.mark.anyio
async def test_get_active_ignores_expired_records(idemp_session: AsyncSession) -> None:
    """Expired records must not be returned by get_active()."""
    repo = IdempotencyRepository(idemp_session)
    key = "expired-key"
    base_now = _utcnow_naive()

    expired = IdempotencyKey.new_started(
        key=key,
        request_hash="hash-1",
        method="POST",
        path="/idempotent",
        ttl_seconds=10,
        now=base_now - timedelta(days=2),
    )
    idemp_session.add(expired)
    await idemp_session.commit()

    result = await repo.get_active(key, now=base_now)
    assert result is None


@pytest.mark.anyio
async def test_get_active_returns_record_within_ttl(idemp_session: AsyncSession) -> None:
    """Records within TTL must be returned by get_active()."""
    repo = IdempotencyRepository(idemp_session)
    key = "active-key"
    now = _utcnow_naive()

    active = IdempotencyKey.new_started(
        key=key,
        request_hash="hash-2",
        method="POST",
        path="/idempotent",
        ttl_seconds=3600,
        now=now,
    )
    idemp_session.add(active)
    await idemp_session.commit()

    result = await repo.get_active(key, now=now + timedelta(seconds=30))
    assert result is not None
    assert result.key == key
    assert result.request_hash == "hash-2"


@pytest.mark.anyio
async def test_save_result_persists_response(idemp_session: AsyncSession) -> None:
    """save_result() must persist status_code, body and state=COMPLETED."""
    repo = IdempotencyRepository(idemp_session)
    key = "save-result-key"
    now = _utcnow_naive()

    started = IdempotencyKey.new_started(
        key=key,
        request_hash="hash-3",
        method="POST",
        path="/idempotent",
        ttl_seconds=3600,
        now=now,
    )
    idemp_session.add(started)
    await idemp_session.commit()

    payload: Mapping[str, Any] = {"ok": True, "value": 123}
    await repo.save_result(
        started,
        status_code=201,
        response_body=payload,
        now=now + timedelta(seconds=5),
    )

    refreshed = await repo.get_active(key, now=now + timedelta(seconds=10))
    assert refreshed is not None
    assert refreshed.state == "COMPLETED"
    assert refreshed.status_code == 201
    assert refreshed.response_body == {"ok": True, "value": 123}
