# src/arche_api/adapters/repositories/staging_repository.py
# Copyright (c)
# SPDX-License-Identifier: MIT
"""Staging repository for idempotent ingests and replayable payloads."""

from __future__ import annotations

from datetime import datetime
from typing import Any
from uuid import UUID, uuid4

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from arche_api.domain.interfaces.repositories.staging_repository import IngestKey
from arche_api.infrastructure.database.models.staging import IngestRun, RawPayload

from .base_repository import BaseRepository

__all__ = ["IngestKey", "StagingRepository"]


class StagingRepository(BaseRepository[Any]):
    """Repository for ingest bookkeeping and raw payload storage."""

    def __init__(self, session: AsyncSession) -> None:
        """Initialize repository.

        Args:
            session: Async SQLAlchemy session.
        """
        super().__init__(session)

    async def start_run(self, k: IngestKey) -> UUID:
        """Create a new ingest run or return an existing one.

        This is **logically idempotent** for a given ``(source, endpoint, key)``:

            • If a run already exists for the tuple, return its ``run_id``.
            • Otherwise, insert a new row and return the new ``run_id``.

        Determinism:
            When resolving an existing run, we order by
            ``started_at DESC NULLS LAST, run_id ASC`` so that in the presence
            of duplicate rows (e.g. legacy or manual inserts) we always pick
            the same winner.

        Note:
            There is currently no database-level unique constraint on
            ``(source, endpoint, key)``, so this method does not use
            ``ON CONFLICT``. Concurrency races are out of scope for this phase.
        """
        # First try to find an existing run deterministically.
        stmt_existing = select(IngestRun).where(
            IngestRun.source == k.source,
            IngestRun.endpoint == k.endpoint,
            IngestRun.key == k.key,
        )
        stmt_existing = self.order_by_created(
            stmt_existing,
            IngestRun.started_at,
            IngestRun.run_id,
        ).limit(1)

        existing = await self.fetch_optional(stmt_existing)
        if existing is not None:
            return existing.run_id

        # No existing run; create a new one.
        run_id = uuid4()
        rec = IngestRun(
            run_id=run_id,
            source=k.source,
            endpoint=k.endpoint,
            key=k.key,
            started_at=self.utc_now(),
        )
        self._session.add(rec)
        return run_id

    async def finish_run(self, run_id: UUID, result: str, error_reason: str | None = None) -> None:
        """Mark an ingest run finished.

        Args:
            run_id: Run identifier.
            result: Result code (SUCCESS|NOOP|ERROR).
            error_reason: Optional error reason.
        """
        stmt = select(IngestRun).where(IngestRun.run_id == run_id)
        rec = await self.fetch_optional(stmt)
        if rec is not None:
            rec.finished_at = self.utc_now()
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
            received_at=self.utc_now(),
            payload=payload,
            as_of=as_of,
            window_from=window_from,
            window_to=window_to,
        )
        self._session.add(rec)
        return rec.payload_id
