# src/stacklion_api/domain/interfaces/repositories/staging_repository.py
# Copyright (c)
# SPDX-License-Identifier: MIT
"""Domain-facing interface for staging repositories.

This module defines:

* IngestKey: canonical dedupe key for ingest runs.
* StagingRepository: protocol describing the capabilities required from
  staging / raw payload repositories.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Any, Protocol
from uuid import UUID


@dataclass(frozen=True)
class IngestKey:
    """Canonical dedupe key for an ingest run.

    Attributes:
        source: Provider name (e.g. ``"marketstack"`` or ``"edgar"``).
        endpoint: Logical endpoint name (e.g. ``"intraday"``).
        key: Stable dedupe key (e.g. symbol+window).
    """

    source: str
    endpoint: str
    key: str


class StagingRepository(Protocol):
    """Domain-level contract for staging repositories."""

    async def start_run(self, k: IngestKey) -> UUID:
        """Create a new ingest run or return an existing one.

        Args:
            k: Ingest dedupe key.

        Returns:
            Run UUID (new or existing).
        """

        raise NotImplementedError

    async def finish_run(self, run_id: UUID, result: str, error_reason: str | None = None) -> None:
        """Mark an ingest run finished.

        Args:
            run_id: Run identifier.
            result: Result code (e.g. ``"SUCCESS"`` | ``"NOOP"`` | ``"ERROR"``).
            error_reason: Optional error reason for failed runs.
        """

        raise NotImplementedError

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

        raise NotImplementedError
