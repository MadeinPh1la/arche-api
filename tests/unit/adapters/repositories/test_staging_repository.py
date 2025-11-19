# tests/integration/repositories/test_staging_repository.py
from __future__ import annotations

import os
from datetime import UTC, datetime, timedelta
from uuid import UUID

import pytest
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from stacklion_api.adapters.repositories.staging_repository import IngestKey, StagingRepository
from stacklion_api.infrastructure.database.models.staging import IngestRun, RawPayload

TEST_DATABASE_URL = os.getenv(
    "DATABASE_URL",
    "postgresql+asyncpg://stacklion:stacklion@127.0.0.1:5432/stacklion_test",
)


@pytest.mark.anyio
async def test_start_run_is_idempotent_and_deterministic() -> None:
    """start_run must be idempotent for a given (source, endpoint, key)."""
    engine = create_async_engine(TEST_DATABASE_URL)
    Session = async_sessionmaker(engine, expire_on_commit=False, class_=AsyncSession)

    async with Session() as session:
        repo = StagingRepository(session)
        key = IngestKey(source="marketstack", endpoint="/intraday", key="MSFT:window")

        run_id_1: UUID = await repo.start_run(key)
        run_id_2: UUID = await repo.start_run(key)

        assert run_id_1 == run_id_2

        # Ensure the persisted record matches the returned run_id.
        db_run = await session.get(IngestRun, run_id_1)
        assert db_run is not None
        assert db_run.source == key.source
        assert db_run.endpoint == key.endpoint
        assert db_run.key == key.key
        assert isinstance(db_run.started_at, datetime)


@pytest.mark.anyio
async def test_finish_run_sets_audit_fields() -> None:
    """finish_run must populate finished_at, result, and error_reason."""
    engine = create_async_engine(TEST_DATABASE_URL)
    Session = async_sessionmaker(engine, expire_on_commit=False, class_=AsyncSession)

    async with Session() as session:
        repo = StagingRepository(session)
        key = IngestKey(source="edgar", endpoint="/filings", key="0000320193")

        run_id = await repo.start_run(key)
        before = await session.get(IngestRun, run_id)
        assert before is not None
        assert before.finished_at is None

        await repo.finish_run(run_id, result="ERROR", error_reason="boom")

        after = await session.get(IngestRun, run_id)
        assert after is not None
        assert after.result == "ERROR"
        assert after.error_reason == "boom"
        assert after.finished_at is not None
        assert after.finished_at >= before.started_at


@pytest.mark.anyio
async def test_save_raw_payload_sets_received_at_and_round_trips() -> None:
    """save_raw_payload must set received_at and persist payload data."""
    engine = create_async_engine(TEST_DATABASE_URL)
    Session = async_sessionmaker(engine, expire_on_commit=False, class_=AsyncSession)

    async with Session() as session:
        repo = StagingRepository(session)
        as_of = datetime.now(UTC) - timedelta(days=1)

        payload_id = await repo.save_raw_payload(
            source="marketstack",
            endpoint="/intraday",
            symbol_or_cik="MSFT",
            etag="etag-123",
            payload={"k": "v"},
            as_of=as_of,
        )

        db_payload = await session.get(RawPayload, payload_id)
        assert db_payload is not None
        assert db_payload.source == "marketstack"
        assert db_payload.endpoint == "/intraday"
        assert db_payload.symbol_or_cik == "MSFT"
        assert db_payload.etag == "etag-123"
        assert db_payload.as_of == as_of
        assert db_payload.payload == {"k": "v"}
        assert isinstance(db_payload.received_at, datetime)
