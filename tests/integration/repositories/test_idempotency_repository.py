# tests/integration/repositories/test_idempotency_repository.py
# Copyright (c) Stacklion.
# SPDX-License-Identifier: MIT
"""
Integration tests for the SQLAlchemy IdempotencyRepository implementation.

These tests operate directly against the database using the IdempotencyKey ORM
model and the concrete repository to verify TTL and result persistence.
"""

from __future__ import annotations

import os
from collections.abc import AsyncGenerator, Mapping
from datetime import datetime, timedelta
from typing import Any
from uuid import uuid4

import pytest
from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)

from stacklion_api.adapters.repositories.idempotency_repository import IdempotencyRepository
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
    database_url = os.getenv(
        "DATABASE_URL",
        "postgresql+asyncpg://stacklion:stacklion@127.0.0.1:5432/stacklion_test",
    )
    engine: AsyncEngine = create_async_engine(database_url, future=True)

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
async def test_get_active_returns_none_when_no_record(idemp_session: AsyncSession) -> None:
    """get_active() must return None when no record exists for the key."""
    repo = IdempotencyRepository(idemp_session)
    result = await repo.get_active("non-existent-key-" + str(uuid4()), now=_utcnow_naive())
    assert result is None


@pytest.mark.anyio
async def test_get_active_ignores_expired_records(idemp_session: AsyncSession) -> None:
    """Expired records must not be returned by get_active()."""
    repo = IdempotencyRepository(idemp_session)
    key = "expired-key-" + str(uuid4())
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
    key = "active-key-" + str(uuid4())
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
async def test_create_started_persists_started_record_and_ttl(idemp_session: AsyncSession) -> None:
    """create_started() must persist a STARTED record with a TTL window."""
    repo = IdempotencyRepository(idemp_session)
    key = "started-key-" + str(uuid4())
    now = _utcnow_naive()
    ttl_seconds = 600

    record = await repo.create_started(
        key=key,
        request_hash="hash-4",
        method="POST",
        path="/idempotent",
        ttl_seconds=ttl_seconds,
        now=now,
    )

    assert record.key == key
    assert record.method == "POST"
    assert record.path == "/idempotent"
    assert record.state == "STARTED"
    delta = record.expires_at - now
    assert 0 < delta.total_seconds() <= ttl_seconds + 5

    refreshed = await repo.get_active(key, now=now + timedelta(seconds=1))
    assert refreshed is not None
    assert refreshed.key == key
    assert refreshed.state == "STARTED"


@pytest.mark.anyio
async def test_save_result_persists_response(idemp_session: AsyncSession) -> None:
    """save_result() must persist status_code, body and state=COMPLETED."""
    repo = IdempotencyRepository(idemp_session)
    key = "save-result-key-" + str(uuid4())
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


@pytest.mark.anyio
async def test_save_result_allows_none_body(idemp_session: AsyncSession) -> None:
    """save_result() must handle None response bodies cleanly."""
    repo = IdempotencyRepository(idemp_session)
    key = "save-result-none-body-key-" + str(uuid4())
    now = _utcnow_naive()

    started = IdempotencyKey.new_started(
        key=key,
        request_hash="hash-5",
        method="POST",
        path="/idempotent",
        ttl_seconds=3600,
        now=now,
    )
    idemp_session.add(started)
    await idemp_session.commit()

    await repo.save_result(
        started,
        status_code=204,
        response_body=None,
        now=now + timedelta(seconds=5),
    )

    refreshed = await repo.get_active(key, now=now + timedelta(seconds=10))
    assert refreshed is not None
    assert refreshed.state == "COMPLETED"
    assert refreshed.status_code == 204
    assert refreshed.response_body is None
