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

    All timestamps are stored as naive UTC to match TIMESTAMP WITHOUT TIME ZONE
    columns in the database. Callers may override `now` when tighter control
    is required (e.g., tests).
"""

from __future__ import annotations

from collections.abc import Mapping
from datetime import datetime, timedelta
from typing import Any, cast

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from stacklion_api.adapters.repositories.base_repository import BaseRepository
from stacklion_api.domain.interfaces.repositories.idempotency_repository import (
    IdempotencyRecord,
)
from stacklion_api.infrastructure.database.models.idempotency import IdempotencyKey


def _utcnow_naive() -> datetime:
    """Return a naive datetime representing current UTC time.

    Returns:
        A naive `datetime` in UTC, suitable for TIMESTAMP WITHOUT TIME ZONE
        columns.
    """
    return datetime.utcnow()


class IdempotencyRepository(BaseRepository[IdempotencyKey]):
    """SQLAlchemy-backed implementation of the idempotency repository contract."""

    def __init__(self, session: AsyncSession) -> None:
        """Initialize the repository.

        Args:
            session: Async SQLAlchemy session bound to the primary database.
        """
        super().__init__(session=session)

    async def get_active(
        self,
        key: str,
        *,
        now: datetime | None = None,
    ) -> IdempotencyRecord | None:
        """Return the active idempotency record for a key, if any.

        Active records are those with ``expires_at >= now``.

        Args:
            key: Idempotency-Key header value.
            now: Optional reference time (naive UTC) used for TTL evaluation. If
                not provided, the current naive UTC time is used.

        Returns:
            Matching idempotency record if active, otherwise None.
        """
        if now is None:
            now = _utcnow_naive()

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

        If a record already exists for this key (expired or not), it will be
        reused and reset instead of inserting a new row. This avoids violating
        the primary key constraint on ``key`` while still allowing keys to be
        reused after TTL expiry.

        Args:
            key: Idempotency-Key header value.
            request_hash: Deterministic hash of method/path/query/body.
            method: HTTP method (e.g. POST).
            path: Request path (no scheme/host).
            ttl_seconds: TTL duration in seconds.
            now: Optional reference time (naive UTC) used for expiry calculation.
                If not provided, the current naive UTC time is used.

        Returns:
            Newly created or reset idempotency record.
        """
        if now is None:
            now = _utcnow_naive()

        # Reuse any existing row for this key (expired or not) to avoid
        # PK collisions on the `key` column.
        stmt = select(IdempotencyKey).where(IdempotencyKey.key == key).limit(1)
        result = await self._session.execute(stmt)
        existing = result.scalar_one_or_none()

        if existing is None:
            record = IdempotencyKey.new_started(
                key=key,
                request_hash=request_hash,
                method=method,
                path=path,
                ttl_seconds=ttl_seconds,
                now=now,
            )
            self._session.add(record)
        else:
            # Reset existing record to a fresh STARTED state.
            existing.request_hash = request_hash
            existing.method = method
            existing.path = path
            existing.status_code = None
            existing.response_body = None
            existing.state = "STARTED"
            existing.created_at = now
            existing.updated_at = now
            existing.expires_at = now + timedelta(seconds=ttl_seconds)
            record = existing

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
            now: Optional reference time (naive UTC) used for ``updated_at``.
                If not provided, the current naive UTC time is used.

        Returns:
            None. The record is committed to the database.
        """
        if now is None:
            now = _utcnow_naive()

        # The underlying instance is an ORM model that structurally satisfies
        # IdempotencyRecord; we mutate it in place and commit.
        record.status_code = status_code
        record.response_body = dict(response_body) if response_body is not None else None
        record.state = "COMPLETED"
        record.updated_at = now

        self._session.add(cast(IdempotencyKey, record))
        await self._session.flush()
        await self._session.commit()
