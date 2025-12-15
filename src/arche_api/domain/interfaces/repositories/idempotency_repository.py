# src/arche_api/domain/interfaces/repositories/idempotency_repository.py
# Copyright (c) Arche.
# SPDX-License-Identifier: MIT
"""Idempotency Repository Interfaces.

Purpose:
    Define domain-level contracts for idempotency dedupe storage and retrieval.
    Keep the domain layer decoupled from the persistence technology.

Layer:
    domain

Notes:
    Implementations live in adapters/infrastructure and must satisfy these
    Protocols via structural typing.
"""

from __future__ import annotations

from collections.abc import Mapping
from datetime import datetime
from typing import Any, Protocol, runtime_checkable


@runtime_checkable
class IdempotencyRecord(Protocol):
    """Shape of an idempotency record.

    Attributes:
        key: Client-supplied Idempotency-Key value.
        request_hash: Deterministic hash of method/path/query/body.
        method: HTTP method (e.g. POST, PUT).
        path: Request path (no scheme/host).
        status_code: HTTP status code for the completed response, if any.
        response_body: JSON response body for the completed response, if any.
        state: Lifecycle state (e.g. "STARTED", "COMPLETED").
        created_at: UTC timestamp when the record was created.
        updated_at: UTC timestamp of the last update.
        expires_at: UTC timestamp after which the record is no longer active.
    """

    key: str
    request_hash: str
    method: str
    path: str
    status_code: int | None
    response_body: dict[str, Any] | None
    state: str
    created_at: datetime
    updated_at: datetime
    expires_at: datetime


class IdempotencyRepository(Protocol):
    """Domain-level contract for idempotency storage.

    Implementations are responsible for:

    * Enforcing a time-to-live (TTL) window for active idempotency keys.
    * Persisting STARTED and COMPLETED records.
    * Returning active records by key.
    """

    async def get_active(
        self, key: str, *, now: datetime | None = None
    ) -> IdempotencyRecord | None:
        """Return the active idempotency record for a key, if any.

        Args:
            key: Idempotency-Key header value.
            now: Optional reference time (UTC) used for TTL checks.

        Returns:
            An IdempotencyRecord if the key is active, otherwise None.
        """
        raise NotImplementedError

    async def create_started(
        self,
        *,
        key: str,
        request_hash: str,
        method: str,
        path: str,
        ttl_seconds: int,
        now: datetime | None = None,
    ) -> IdempotencyRecord:
        """Create a new STARTED idempotency record.

        Args:
            key: Idempotency-Key header value.
            request_hash: Deterministic hash of method/path/query/body.
            method: HTTP method (e.g. POST).
            path: Request path (no scheme/host).
            ttl_seconds: TTL window duration in seconds.
            now: Optional reference time (UTC) used for expiry calculation.

        Returns:
            The newly created IdempotencyRecord.
        """
        raise NotImplementedError

    async def save_result(
        self,
        record: IdempotencyRecord,
        *,
        status_code: int,
        response_body: Mapping[str, Any] | None,
        now: datetime | None = None,
    ) -> None:
        """Persist the final result for an idempotent operation.

        Args:
            record: The idempotency record to update.
            status_code: HTTP status code of the completed response.
            response_body: JSON response body of the completed response.
            now: Optional reference time (UTC) used for updated_at.

        Returns:
            None. Implementations must persist the update.
        """
        raise NotImplementedError
