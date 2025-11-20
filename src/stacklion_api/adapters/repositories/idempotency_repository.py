# src/stacklion_api/adapters/repositories/idempotency_repository.py
# Copyright (c) Stacklion.
# SPDX-License-Identifier: MIT
"""
Idempotency Repository (SQLAlchemy).

Purpose:
    Provide a concrete SQLAlchemy implementation of the idempotency repository
    contract defined in the domain layer.

Layer:
    adapters

Notes:
    This repository operates on `IdempotencyKey` ORM models and satisfies the
    `IdempotencyRepository` Protocol via structural typing.
"""

from __future__ import annotations

from collections.abc import Mapping
from datetime import UTC, datetime
from typing import Any, cast

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from stacklion_api.domain.interfaces.repositories.idempotency_repository import (
    IdempotencyRecord,
)
from stacklion_api.infrastructure.database.models.idempotency import IdempotencyKey


class IdempotencyRepository:
    """SQLAlchemy-backed implementation of the idempotency repository contract."""

    def __init__(self, session: AsyncSession) -> None:
        """Initialize the repository.

        Args:
            session: Async SQLAlchemy session bound to the primary database.
        """
        self._session = session

    async def get_active(
        self, key: str, *, now: datetime | None = None
    ) -> IdempotencyRecord | None:
        """Return the active idempotency record for a key, if any.

        Active records are those with ``expires_at >= now``.

        Args:
            key: Idempotency-Key header value.
            now: Optional reference time (UTC) used for TTL evaluation.

        Returns:
            IdempotencyRecord | None: Matching record if active, otherwise None.
        """
        if now is None:
            now = datetime.now(UTC)

        stmt = (
            select(IdempotencyKey)
            .where(IdempotencyKey.key == key, IdempotencyKey.expires_at >= now)
            .limit(1)
        )
        result = await self._session.execute(stmt)
        record = result.scalar_one_or_none()
        return cast(IdempotencyRecord | None, record)

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
        """Create and persist a new STARTED idempotency record.

        Args:
            key: Idempotency-Key header value.
            request_hash: Deterministic hash of method/path/query/body.
            method: HTTP method (e.g. POST).
            path: Request path (no scheme/host).
            ttl_seconds: TTL duration in seconds.
            now: Optional reference time (UTC) used for expiry calculation.

        Returns:
            IdempotencyRecord: Newly created record.
        """
        record = IdempotencyKey.new_started(
            key=key,
            request_hash=request_hash,
            method=method,
            path=path,
            ttl_seconds=ttl_seconds,
            now=now,
        )
        self._session.add(record)
        await self._session.flush()
        # Commit so concurrent requests observe the STARTED record.
        await self._session.commit()
        return cast(IdempotencyRecord, record)

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
            record: Idempotency record to update.
            status_code: HTTP status code for the completed response.
            response_body: JSON response payload for the completed response.
            now: Optional reference time (UTC) used for ``updated_at``.

        Returns:
            None. The record is committed to the database.
        """
        if now is None:
            now = datetime.now(UTC)

        # The underlying instance is an ORM model that structurally satisfies
        # IdempotencyRecord; we mutate it in place and commit.
        record.status_code = status_code
        record.response_body = dict(response_body) if response_body is not None else None
        record.state = "COMPLETED"
        record.updated_at = now

        self._session.add(cast(IdempotencyKey, record))
        await self._session.flush()
        await self._session.commit()
