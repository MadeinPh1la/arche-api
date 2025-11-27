# src/stacklion_api/application/use_cases/external_apis/edgar/ingest_edgar_filings.py
# Copyright (c)
# SPDX-License-Identifier: MIT
"""Use case: Ingest recent EDGAR filings (raw stage only).

Stores raw payloads under staging for replay and later mapping.

Scope:
    * Best-effort fetch of "recent filings" JSON for a single CIK.
    * Persist raw provider payload into the staging schema.
    * Mark ingest runs as SUCCESS / ERROR for idempotent replay.

This use case deliberately avoids mapping into domain entities. It exists to
bootstrap EDGAR ingest plumbing; a later phase can add:
    * Shape validation
    * Projection into normalized filing tables
    * Backfill / replay tooling
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
from importlib import import_module
from typing import Any, Protocol

from sqlalchemy.ext.asyncio import AsyncSession


class EdgarGateway(Protocol):
    """Protocol for an EDGAR gateway returning recent filings JSON."""

    async def fetch_recent_filings(self, *, cik: str, limit: int = 100) -> dict[str, Any]:
        """Fetch recent EDGAR filings for a single company.

        Args:
            cik: Zero-padded CIK for the company.
            limit: Maximum number of filings to return.

        Returns:
            Raw JSON mapping as returned by the EDGAR client or gateway.
        """
        ...


@dataclass(frozen=True)
class IngestEdgarRequest:
    """Request parameters for EDGAR ingest."""

    cik: str


class IngestEdgarFilings:
    """Ingest EDGAR recent filings (raw stage only)."""

    def __init__(self, gateway: EdgarGateway) -> None:
        """Initialize the use case.

        Args:
            gateway: EDGAR gateway implementation.
        """
        self._gateway = gateway

    async def __call__(self, session: AsyncSession, req: IngestEdgarRequest) -> int:
        """Execute the EDGAR ingest.

        Args:
            session: Database session.
            req: Ingest parameters.

        Returns:
            Number of filings discovered (best effort).
        """
        staging_module = import_module("stacklion_api.adapters.repositories.staging_repository")
        StagingRepository = staging_module.StagingRepository
        IngestKey = staging_module.IngestKey

        staging = StagingRepository(session)
        key = IngestKey(source="edgar", endpoint="recent_filings", key=req.cik)
        run_id = await staging.start_run(key)

        try:
            payload = await self._gateway.fetch_recent_filings(cik=req.cik, limit=100)

            # Persist the raw provider payload for deterministic replay.
            await staging.save_raw_payload(
                source="edgar",
                endpoint="recent_filings",
                symbol_or_cik=req.cik,
                etag=None,
                payload=payload,
                as_of=datetime.now(tz=UTC),
                window_from=None,
                window_to=None,
            )

            # Heuristic count: look for a "filings" list; otherwise zero.
            count = 0
            if isinstance(payload, dict):
                filings = payload.get("filings")
                if isinstance(filings, list):
                    count = len(filings)

            await staging.finish_run(run_id, result="SUCCESS")
            await session.commit()
            return count
        except Exception as exc:  # pragma: no cover
            await staging.finish_run(run_id, result="ERROR", error_reason=type(exc).__name__)
            await session.rollback()
            raise
