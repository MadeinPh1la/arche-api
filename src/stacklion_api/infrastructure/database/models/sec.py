# src/stacklion_api/infrastructure/database/models/sec.py
# Copyright (c) Stacklion.
# SPDX-License-Identifier: MIT
"""SEC / EDGAR ORM models.

Purpose:
    Provide SQLAlchemy ORM mappings for the SEC (EDGAR) schema, including:

    * ``sec.filings``: Filing metadata keyed by accession, linked to
      ``ref.companies``.
    * ``sec.statement_versions``: Versioned financial statement metadata
      (income, balance sheet, cash flow) tied to filings.

Design:
    - The schema is metadata-only for statements in this phase; line items and
      dimensional data will be modeled in later phases.
    - Filings are keyed by a UUID primary key with ``accession`` as a unique
      natural key to support idempotent ingests.
    - Statement versions use a UUID primary key and a composite identity:
        (company_id, statement_type, statement_date, version_sequence)
      enforced at the database level.

Layer:
    infrastructure / database / models
"""

from __future__ import annotations

from datetime import date, datetime
from typing import Any
from uuid import UUID

from sqlalchemy import (
    JSON,
    Boolean,
    Date,
    DateTime,
    ForeignKey,
    Integer,
    String,
    Text,
    UniqueConstraint,
    text,
)
from sqlalchemy.orm import Mapped, mapped_column

from stacklion_api.infrastructure.database.models.base import Base


class Filing(Base):
    """SEC / EDGAR filing metadata (sec.filings)."""

    __tablename__ = "filings"
    __table_args__ = ({"schema": "sec"},)

    filing_id: Mapped[UUID] = mapped_column(primary_key=True)

    company_id: Mapped[UUID | None] = mapped_column(
        ForeignKey("ref.companies.company_id"),
        nullable=True,
    )

    cik: Mapped[str] = mapped_column(String(10), nullable=False)
    accession: Mapped[str] = mapped_column(String(32), nullable=False, unique=True)
    form_type: Mapped[str] = mapped_column(String(16), nullable=False)
    filed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    period_of_report: Mapped[date | None] = mapped_column(Date, nullable=True)

    # Back column name is "metadata" but Python attribute is "filing_metadata"
    # to avoid clashing with SQLAlchemy's DeclarativeBase.metadata.
    filing_metadata: Mapped[dict[str, Any] | None] = mapped_column(
        "metadata",
        JSON,
        nullable=True,
    )

    is_amendment: Mapped[bool] = mapped_column(
        Boolean,
        nullable=False,
        default=False,
        server_default=text("false"),
    )
    amendment_sequence: Mapped[int | None] = mapped_column(Integer, nullable=True)
    primary_document: Mapped[str | None] = mapped_column(String(256), nullable=True)
    accepted_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
    )
    filing_url: Mapped[str | None] = mapped_column(Text, nullable=True)
    data_source: Mapped[str] = mapped_column(
        String(16),
        nullable=False,
        default="EDGAR",
        server_default=text("'EDGAR'"),
    )


class StatementVersion(Base):
    """Versioned financial statement metadata (sec.statement_versions)."""

    __tablename__ = "statement_versions"
    __table_args__ = (
        UniqueConstraint(
            "company_id",
            "statement_type",
            "statement_date",
            "version_sequence",
            name="uq_statement_identity_version",
        ),
        {"schema": "sec"},
    )  # type: ignore[assignment]

    statement_version_id: Mapped[UUID] = mapped_column(primary_key=True)

    company_id: Mapped[UUID] = mapped_column(
        ForeignKey("ref.companies.company_id"),
        nullable=False,
    )
    filing_id: Mapped[UUID] = mapped_column(
        ForeignKey("sec.filings.filing_id"),
        nullable=False,
    )

    statement_type: Mapped[str] = mapped_column(String(32), nullable=False)
    accounting_standard: Mapped[str] = mapped_column(String(32), nullable=False)
    statement_date: Mapped[date] = mapped_column(Date, nullable=False)
    fiscal_year: Mapped[int] = mapped_column(Integer, nullable=False)
    fiscal_period: Mapped[str] = mapped_column(String(8), nullable=False)
    currency: Mapped[str] = mapped_column(String(16), nullable=False)

    is_restated: Mapped[bool] = mapped_column(
        Boolean,
        nullable=False,
        default=False,
        server_default=text("false"),
    )
    restatement_reason: Mapped[str | None] = mapped_column(String(255), nullable=True)

    version_source: Mapped[str] = mapped_column(String(64), nullable=False)
    version_sequence: Mapped[int] = mapped_column(Integer, nullable=False)

    # Normalized statement payload (Bloomberg-class, modeling-ready).
    # Stored as JSONB for flexibility, with a separate version field to allow
    # schema evolution over time.
    normalized_payload: Mapped[dict[str, Any] | None] = mapped_column(
        JSON,
        nullable=True,
    )
    normalized_payload_version: Mapped[str] = mapped_column(
        String(16),
        nullable=False,
        server_default=text("'v1'"),
    )

    accession_id: Mapped[str] = mapped_column(String(32), nullable=False)
    filing_date: Mapped[date] = mapped_column(Date, nullable=False)

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=text("now()"),
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=text("now()"),
    )
