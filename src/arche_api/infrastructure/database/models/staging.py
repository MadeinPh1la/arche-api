# Copyright (c) Arche.
# SPDX-License-Identifier: MIT
"""Staging models for ingest bookkeeping and replayable payload storage."""

from __future__ import annotations

from datetime import datetime
from typing import Any
from uuid import UUID

from sqlalchemy import JSON, DateTime, String
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column


class Base(DeclarativeBase):
    """Declarative base for staging models."""

    pass


class IngestRun(Base):
    """An ingest run record for idempotency and auditing."""

    __tablename__ = "ingest_runs"
    __table_args__ = {"schema": "staging"}

    run_id: Mapped[UUID] = mapped_column(primary_key=True)
    source: Mapped[str] = mapped_column(String(32))
    endpoint: Mapped[str] = mapped_column(String(64))
    key: Mapped[str] = mapped_column(String(256))
    started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    result: Mapped[str | None] = mapped_column(String(16))
    error_reason: Mapped[str | None] = mapped_column(String(256))


class RawPayload(Base):
    """Raw provider payload for deterministic replay.

    Attributes:
        payload: JSON body as delivered by upstream.
        etag: Upstream ETag if provided.
        window_from/window_to: For time-windowed ingests.
    """

    __tablename__ = "raw_payloads"
    __table_args__ = {"schema": "staging"}

    payload_id: Mapped[UUID] = mapped_column(primary_key=True)
    source: Mapped[str] = mapped_column(String(32))
    endpoint: Mapped[str] = mapped_column(String(64))
    symbol_or_cik: Mapped[str | None] = mapped_column(String(64))
    as_of: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    window_from: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    window_to: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    etag: Mapped[str | None] = mapped_column(String(128))
    received_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    payload: Mapped[dict[str, Any]] = mapped_column(JSON)
