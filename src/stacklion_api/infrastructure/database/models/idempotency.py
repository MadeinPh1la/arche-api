# src/stacklion_api/infrastructure/database/models/idempotency.py
# Copyright (c) Stacklion.
# SPDX-License-Identifier: MIT
"""Idempotency Models.

Purpose:
    Provide SQLAlchemy models for HTTP idempotency dedupe records.

Layer:
    infrastructure

Notes:
    This module defines the concrete persistence shape for idempotency keys.
    Domain contracts are defined in
    ``stacklion_api.domain.interfaces.repositories.idempotency_repository``.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Any

from sqlalchemy import Index, String
from sqlalchemy.orm import Mapped, mapped_column

from stacklion_api.infrastructure.database.models.base import (
    Base,
    JSONBType,
    ReprMixin,
    SerializationMixin,
    now_utc,
)


class IdempotencyKey(Base, ReprMixin, SerializationMixin):
    """Persistence model for HTTP idempotency dedupe records.

    Attributes:
        key: Client-supplied Idempotency-Key header value (primary key).
        request_hash: Deterministic hash of method/path/query/body.
        method: HTTP method (e.g. POST, PUT).
        path: Normalized request path (no scheme/host).
        status_code: HTTP status code for the completed response, if any.
        response_body: JSON payload returned to the client, if any.
        state: Lifecycle state (e.g. "STARTED", "COMPLETED").
        created_at: UTC timestamp when the record was created.
        updated_at: UTC timestamp of the last update.
        expires_at: UTC timestamp after which the record is inactive.
    """

    __tablename__ = "idempotency_keys"

    key: Mapped[str] = mapped_column(
        String(length=255),
        primary_key=True,
        nullable=False,
        doc="Raw Idempotency-Key header value.",
    )
    request_hash: Mapped[str] = mapped_column(
        String(length=128),
        nullable=False,
        doc="Deterministic hash of method/path/query/body.",
    )
    method: Mapped[str] = mapped_column(
        String(length=16),
        nullable=False,
        doc="HTTP method used for the request.",
    )
    path: Mapped[str] = mapped_column(
        String(length=255),
        nullable=False,
        doc="Request path (no scheme or host).",
    )
    status_code: Mapped[int | None] = mapped_column(
        nullable=True,
        doc="Final HTTP status code for the completed response.",
    )
    response_body: Mapped[dict[str, Any] | None] = mapped_column(
        JSONBType,
        nullable=True,
        doc="JSON response payload for the completed response.",
    )
    state: Mapped[str] = mapped_column(
        String(length=16),
        nullable=False,
        default="STARTED",
        doc='Lifecycle state (e.g. "STARTED", "COMPLETED").',
    )
    created_at: Mapped[datetime] = mapped_column(
        nullable=False,
        default=now_utc,
        doc="UTC timestamp when the record was created.",
    )
    updated_at: Mapped[datetime] = mapped_column(
        nullable=False,
        default=now_utc,
        doc="UTC timestamp when the record was last updated.",
    )
    expires_at: Mapped[datetime] = mapped_column(
        nullable=False,
        doc="UTC timestamp after which this record is ignored.",
    )

    # mypy's Base.__table_args__ type is narrow (dict-only tuple); this is a
    # standard pattern in this codebase and is safe in practice.
    __table_args__ = (  # type: ignore[assignment]
        Index("ix_idempotency_keys_expires_at", "expires_at"),
    )

    @classmethod
    def new_started(
        cls,
        *,
        key: str,
        request_hash: str,
        method: str,
        path: str,
        ttl_seconds: int,
        now: datetime | None = None,
    ) -> IdempotencyKey:
        """Create a new STARTED idempotency record.

        Args:
            key: Raw Idempotency-Key header value.
            request_hash: Deterministic hash of method/path/query/body.
            method: HTTP method (e.g. POST).
            path: Request path (no scheme/host).
            ttl_seconds: TTL duration in seconds.
            now: Optional reference time (UTC) for deterministic tests.

        Returns:
            IdempotencyKey: New instance with state STARTED and expires_at set
            according to the TTL.
        """
        if now is None:
            now = datetime.now(UTC)
        return cls(
            key=key,
            request_hash=request_hash,
            method=method,
            path=path,
            state="STARTED",
            created_at=now,
            updated_at=now,
            expires_at=now + timedelta(seconds=int(ttl_seconds)),
        )
