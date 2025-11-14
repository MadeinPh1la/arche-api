# src/stacklion_api/adapters/repositories/staging_repository.py
# Copyright (c) Stacklion.
# SPDX-License-Identifier: MIT
"""Staging repository for idempotent ingests and replayable payloads."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any
from uuid import UUID, uuid4

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from stacklion_api.infrastructure.database.models.staging import IngestRun, RawPayload


@dataclass(frozen=True)
class IngestKey:
    """Canonical dedupe key for an ingest run."""

    source: str
    endpoint: str
    key: str  # e.g. "MSFT:2025-11-11T10:00Z-2025-11-11T11:00Z"


class StagingRepository:
    """Repository for ingest bookkeeping and raw payload storage."""

    def __init__(self, session: AsyncSession) -> None:
        """Initialize repository.

        Args:
            session: Async SQLAlchemy session.
        """
        self._session = session

    async def start_run(self, k: IngestKey) -> UUID:
        """Create a new ingest run.

        This method is idempotent with respect to the database-level
        deduplication constraint on ``(source, endpoint, key)``. If a run for
        the same tuple already exists, its ``run_id`` is returned instead of
        raising an integrity error.

        Args:
            k: Ingest key.

        Returns:
            Run UUID (new or existing).
        """
        run_id = uuid4()
        rec = IngestRun(
            run_id=run_id,
            source=k.source,
            endpoint=k.endpoint,
            key=k.key,
            started_at=datetime.now(UTC),
        )
        self._session.add(rec)

        try:
            # Flush eagerly so uniqueness violations surface here rather than
            # later in unrelated operations (e.g. payload insert).
            await self._session.flush()
        except IntegrityError:
            # Another run already claimed this (source, endpoint, key). Roll
            # back the failed transaction and reuse the existing run_id.
            await self._session.rollback()

            res = await self._session.execute(
                select(IngestRun.run_id)
                .where(
                    IngestRun.source == k.source,
                    IngestRun.endpoint == k.endpoint,
                    IngestRun.key == k.key,
                )
                .order_by(IngestRun.started_at.desc())
                .limit(1)
            )
            existing_run_id = res.scalar_one()
            return existing_run_id

        return run_id

    async def finish_run(self, run_id: UUID, result: str, error_reason: str | None = None) -> None:
        """Mark an ingest run finished.

        Args:
            run_id: Run identifier.
            result: Result code (SUCCESS|NOOP|ERROR).
            error_reason: Optional error reason.
        """
        res = await self._session.execute(select(IngestRun).where(IngestRun.run_id == run_id))
        rec = res.scalars().first()
        if rec is not None:
            rec.finished_at = datetime.now(UTC)
            rec.result = result
            rec.error_reason = error_reason

    async def save_raw_payload(
        self,
        *,
        source: str,
        endpoint: str,
        symbol_or_cik: str | None,
        etag: str | None,
        payload: dict[str, Any],
        as_of: datetime | None = None,
        window_from: datetime | None = None,
        window_to: datetime | None = None,
    ) -> UUID:
        """Persist a raw provider payload for replay.

        Args:
            source: Provider name.
            endpoint: Endpoint identifier.
            symbol_or_cik: Symbol ticker or CIK.
            etag: Upstream ETag if any.
            payload: JSON payload.
            as_of: Point-in-time payload.
            window_from: Start of ingest window.
            window_to: End of ingest window.

        Returns:
            The new payload UUID.
        """
        rec = RawPayload(
            payload_id=uuid4(),
            source=source,
            endpoint=endpoint,
            symbol_or_cik=symbol_or_cik,
            etag=etag,
            received_at=datetime.now(UTC),
            payload=payload,
            as_of=as_of,
            window_from=window_from,
            window_to=window_to,
        )
        self._session.add(rec)
        return rec.payload_id
