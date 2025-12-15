# src/arche_api/infrastructure/database/models/sec.py
# Copyright (c)
# SPDX-License-Identifier: MIT
"""SEC / EDGAR ORM models.

Purpose:
    Provide SQLAlchemy ORM mappings for the SEC (EDGAR) schema, including:

    * ``sec.filings``: Filing metadata keyed by accession, linked to
      ``ref.companies``.
    * ``sec.statement_versions``: Versioned financial statement metadata
      (income, balance sheet, cash flow) tied to filings.
    * ``sec.edgar_normalized_facts``: Persistent fact-level storage derived
      from normalized statement payloads.
    * ``sec.edgar_dq_run``: Data-quality evaluation runs.
    * ``sec.edgar_fact_quality``: Fact-level quality flags and severity.
    * ``sec.edgar_dq_anomalies``: Rule-level DQ anomalies.

Design:
    - Filings and statement versions follow the existing metadata-focused
      model.
    - Fact and DQ tables are designed for deterministic ordering and efficient
      access by statement identity and DQ run.
    - UUID primary keys are used where appropriate, with denormalized identity
      columns (e.g., cik, statement_type, fiscal_year) to support common
      query patterns.

Layer:
    infrastructure / database / models
"""

from __future__ import annotations

from datetime import date, datetime
from decimal import Decimal
from typing import Any
from uuid import UUID

from sqlalchemy import (
    JSON,
    Boolean,
    Date,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    Numeric,
    String,
    Text,
    UniqueConstraint,
    text,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from arche_api.infrastructure.database.models.base import Base


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


# --------------------------------------------------------------------------- #
# Normalized fact store (sec.edgar_normalized_facts)                          #
# --------------------------------------------------------------------------- #


class EdgarNormalizedFact(Base):
    """Persistent normalized fact derived from a canonical statement payload."""

    __tablename__ = "edgar_normalized_facts"
    __table_args__ = (
        UniqueConstraint(
            "statement_version_id",
            "metric_code",
            "dimension_key",
            name="uq_edgar_normalized_fact_identity",
        ),
        Index(
            "ix_edgar_normalized_facts_identity",
            "cik",
            "statement_type",
            "fiscal_year",
            "fiscal_period",
            "metric_code",
            "statement_date",
        ),
        {"schema": "sec"},
    )  # type: ignore[assignment]

    fact_id: Mapped[UUID] = mapped_column(primary_key=True)

    statement_version_id: Mapped[UUID] = mapped_column(
        ForeignKey("sec.statement_versions.statement_version_id"),
        nullable=False,
    )
    company_id: Mapped[UUID] = mapped_column(
        ForeignKey("ref.companies.company_id"),
        nullable=False,
    )

    cik: Mapped[str] = mapped_column(String(10), nullable=False)
    statement_type: Mapped[str] = mapped_column(String(32), nullable=False)
    accounting_standard: Mapped[str] = mapped_column(String(32), nullable=False)
    fiscal_year: Mapped[int] = mapped_column(Integer, nullable=False)
    fiscal_period: Mapped[str] = mapped_column(String(8), nullable=False)
    statement_date: Mapped[date] = mapped_column(Date, nullable=False)
    version_sequence: Mapped[int] = mapped_column(Integer, nullable=False)

    metric_code: Mapped[str] = mapped_column(String(64), nullable=False)
    metric_label: Mapped[str | None] = mapped_column(String(255), nullable=True)
    unit: Mapped[str] = mapped_column(String(16), nullable=False)

    period_start: Mapped[date | None] = mapped_column(Date, nullable=True)
    period_end: Mapped[date] = mapped_column(Date, nullable=False)

    value: Mapped[Decimal] = mapped_column(
        Numeric(38, 6),
        nullable=False,
    )

    dimension_key: Mapped[str] = mapped_column(String(128), nullable=False)
    dimension: Mapped[dict[str, Any] | None] = mapped_column(JSON, nullable=True)
    source_line_item: Mapped[str | None] = mapped_column(String(255), nullable=True)

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=text("now()"),
    )


# --------------------------------------------------------------------------- #
# Data-quality: runs, fact quality, anomalies                                 #
# --------------------------------------------------------------------------- #


class EdgarDQRun(Base):
    """Data-quality evaluation run metadata (sec.edgar_dq_run)."""

    __tablename__ = "edgar_dq_run"
    __table_args__ = (
        Index(
            "ix_edgar_dq_run_identity_executed_at",
            "cik",
            "statement_type",
            "fiscal_year",
            "fiscal_period",
            "version_sequence",
            "executed_at",
        ),
        {"schema": "sec"},
    )  # type: ignore[assignment]

    dq_run_id: Mapped[UUID] = mapped_column(primary_key=True)

    statement_version_id: Mapped[UUID | None] = mapped_column(
        ForeignKey("sec.statement_versions.statement_version_id"),
        nullable=True,
    )

    cik: Mapped[str | None] = mapped_column(String(10), nullable=True)
    statement_type: Mapped[str | None] = mapped_column(String(32), nullable=True)
    fiscal_year: Mapped[int | None] = mapped_column(Integer, nullable=True)
    fiscal_period: Mapped[str | None] = mapped_column(String(8), nullable=True)
    version_sequence: Mapped[int | None] = mapped_column(Integer, nullable=True)

    rule_set_version: Mapped[str] = mapped_column(String(32), nullable=False)
    scope_type: Mapped[str] = mapped_column(String(16), nullable=False)

    executed_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=text("now()"),
    )


class EdgarFactQuality(Base):
    """Fact-level quality flags and severity (sec.edgar_fact_quality)."""

    __tablename__ = "edgar_fact_quality"
    __table_args__ = (
        UniqueConstraint(
            "dq_run_id",
            "metric_code",
            "dimension_key",
            name="uq_edgar_fact_quality_identity",
        ),
        Index(
            "ix_edgar_fact_quality_statement_identity",
            "cik",
            "statement_type",
            "fiscal_year",
            "fiscal_period",
            "version_sequence",
            "metric_code",
        ),
        {"schema": "sec"},
    )  # type: ignore[assignment]

    fact_quality_id: Mapped[UUID] = mapped_column(primary_key=True)

    dq_run_id: Mapped[UUID] = mapped_column(
        ForeignKey("sec.edgar_dq_run.dq_run_id"),
        nullable=False,
    )
    statement_version_id: Mapped[UUID | None] = mapped_column(
        ForeignKey("sec.statement_versions.statement_version_id"),
        nullable=True,
    )

    cik: Mapped[str] = mapped_column(String(10), nullable=False)
    statement_type: Mapped[str] = mapped_column(String(32), nullable=False)
    fiscal_year: Mapped[int] = mapped_column(Integer, nullable=False)
    fiscal_period: Mapped[str] = mapped_column(String(8), nullable=False)
    version_sequence: Mapped[int] = mapped_column(Integer, nullable=False)

    metric_code: Mapped[str] = mapped_column(String(64), nullable=False)
    dimension_key: Mapped[str] = mapped_column(String(128), nullable=False)

    severity: Mapped[str] = mapped_column(String(16), nullable=False)

    is_present: Mapped[bool] = mapped_column(Boolean, nullable=False)
    is_non_negative: Mapped[bool | None] = mapped_column(Boolean, nullable=True)
    is_consistent_with_history: Mapped[bool | None] = mapped_column(Boolean, nullable=True)
    has_known_issue: Mapped[bool] = mapped_column(
        Boolean,
        nullable=False,
        default=False,
        server_default=text("false"),
    )

    details: Mapped[dict[str, Any] | None] = mapped_column(JSON, nullable=True)

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=text("now()"),
    )


class EdgarDQAnomaly(Base):
    """Rule-level DQ anomaly (sec.edgar_dq_anomalies)."""

    __tablename__ = "edgar_dq_anomalies"
    __table_args__ = (
        Index(
            "ix_edgar_dq_anomalies_run_severity",
            "dq_run_id",
            "severity",
        ),
        {"schema": "sec"},
    )  # type: ignore[assignment]

    anomaly_id: Mapped[UUID] = mapped_column(primary_key=True)

    dq_run_id: Mapped[UUID] = mapped_column(
        ForeignKey("sec.edgar_dq_run.dq_run_id"),
        nullable=False,
    )
    statement_version_id: Mapped[UUID | None] = mapped_column(
        ForeignKey("sec.statement_versions.statement_version_id"),
        nullable=True,
    )

    metric_code: Mapped[str | None] = mapped_column(String(64), nullable=True)
    dimension_key: Mapped[str | None] = mapped_column(String(128), nullable=True)

    rule_code: Mapped[str] = mapped_column(String(64), nullable=False)
    severity: Mapped[str] = mapped_column(String(16), nullable=False)

    message: Mapped[str] = mapped_column(Text, nullable=False)
    details: Mapped[dict[str, Any] | None] = mapped_column(JSON, nullable=True)

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=text("now()"),
    )


class EdgarStatementAlignment(Base):
    """Statement-level alignment and calendar metadata (sec.edgar_statement_alignment).

    Captures derived calendar attributes and stitching/alignment status for
    a specific `sec.statement_versions` row. Designed to support deterministic
    timelines and reconciliation reporting without re-running stitching logic.
    """

    __tablename__ = "edgar_statement_alignment"
    __table_args__ = (
        UniqueConstraint(
            "statement_version_id",
            name="uq_edgar_statement_alignment_statement_version",
        ),
        Index(
            "ix_edgar_statement_alignment_identity",
            "cik",
            "statement_type",
            "fiscal_year",
            "fiscal_period",
            "version_sequence",
        ),
        {"schema": "sec"},
    )  # type: ignore[assignment]

    alignment_id: Mapped[UUID] = mapped_column(primary_key=True)

    statement_version_id: Mapped[UUID] = mapped_column(
        ForeignKey("sec.statement_versions.statement_version_id"),
        nullable=False,
    )
    company_id: Mapped[UUID] = mapped_column(
        ForeignKey("ref.companies.company_id"),
        nullable=False,
    )

    # Denormalized identity columns to mirror fact store querying patterns.
    cik: Mapped[str] = mapped_column(String(10), nullable=False)
    statement_type: Mapped[str] = mapped_column(String(32), nullable=False)
    fiscal_year: Mapped[int] = mapped_column(Integer, nullable=False)
    fiscal_period: Mapped[str] = mapped_column(String(8), nullable=False)
    statement_date: Mapped[date] = mapped_column(Date, nullable=False)
    version_sequence: Mapped[int] = mapped_column(Integer, nullable=False)

    # Calendar / period metadata.
    fye_date: Mapped[date | None] = mapped_column(Date, nullable=True)
    is_53_week_year: Mapped[bool] = mapped_column(
        Boolean,
        nullable=False,
        default=False,
        server_default=text("false"),
    )
    period_start: Mapped[date | None] = mapped_column(Date, nullable=True)
    period_end: Mapped[date | None] = mapped_column(Date, nullable=True)

    # Alignment / stitching status across IS/BS/CF.
    alignment_status: Mapped[str] = mapped_column(String(32), nullable=False)

    # Flags for irregular / partial periods.
    is_partial_period: Mapped[bool] = mapped_column(
        Boolean,
        nullable=False,
        default=False,
        server_default=text("false"),
    )
    is_off_cycle_period: Mapped[bool] = mapped_column(
        Boolean,
        nullable=False,
        default=False,
        server_default=text("false"),
    )
    is_irregular_calendar: Mapped[bool] = mapped_column(
        Boolean,
        nullable=False,
        default=False,
        server_default=text("false"),
    )

    # Optional diagnostic payload (e.g., stitching notes, inferred calendar).
    details: Mapped[dict[str, Any] | None] = mapped_column(JSON, nullable=True)

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


class EdgarReconciliationCheck(Base):
    """Reconciliation ledger entry (sec.edgar_reconciliation_checks).

    Append-only ledger of rule evaluations produced by the reconciliation engine.
    Designed for deterministic issuer/statement/time queries.
    """

    __tablename__ = "edgar_reconciliation_checks"
    __table_args__ = (
        Index(
            "ix_edgar_recon_checks_identity_run",
            "cik",
            "statement_type",
            "fiscal_year",
            "fiscal_period",
            "version_sequence",
            "reconciliation_run_id",
            "rule_category",
            "rule_id",
            "dimension_key",
        ),
        Index(
            "ix_edgar_recon_checks_run_status",
            "reconciliation_run_id",
            "status",
            "severity",
        ),
        UniqueConstraint(
            "reconciliation_run_id",
            "rule_id",
            "dimension_key",
            name="uq_edgar_recon_checks_run_rule_dimension",
        ),
        {"schema": "sec"},
    )  # type: ignore[assignment]

    check_id: Mapped[UUID] = mapped_column(primary_key=True)

    reconciliation_run_id: Mapped[UUID] = mapped_column(nullable=False)
    executed_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=text("now()"),
    )

    statement_version_id: Mapped[UUID | None] = mapped_column(
        ForeignKey("sec.statement_versions.statement_version_id"),
        nullable=True,
    )
    company_id: Mapped[UUID | None] = mapped_column(
        ForeignKey("ref.companies.company_id"),
        nullable=True,
    )

    # Denormalized identity columns (modeling-friendly)
    cik: Mapped[str] = mapped_column(String(10), nullable=False)
    statement_type: Mapped[str] = mapped_column(String(32), nullable=False)
    fiscal_year: Mapped[int] = mapped_column(Integer, nullable=False)
    fiscal_period: Mapped[str] = mapped_column(String(8), nullable=False)
    version_sequence: Mapped[int] = mapped_column(Integer, nullable=False)

    statement_date: Mapped[date | None] = mapped_column(Date, nullable=True)

    # Rule identity
    rule_id: Mapped[str] = mapped_column(String(128), nullable=False)
    rule_category: Mapped[str] = mapped_column(String(32), nullable=False)

    # Outcome
    status: Mapped[str] = mapped_column(String(16), nullable=False)
    severity: Mapped[str] = mapped_column(String(16), nullable=False)

    # Numeric deltas
    expected_value: Mapped[Decimal | None] = mapped_column(Numeric(38, 6), nullable=True)
    actual_value: Mapped[Decimal | None] = mapped_column(Numeric(38, 6), nullable=True)
    delta_value: Mapped[Decimal | None] = mapped_column(Numeric(38, 6), nullable=True)

    # Dimensional slice (optional)
    dimension_key: Mapped[str | None] = mapped_column(String(128), nullable=True)
    dimension_labels: Mapped[dict[str, Any] | None] = mapped_column(JSONB, nullable=True)

    # Diagnostics (optional)
    notes: Mapped[dict[str, Any] | None] = mapped_column(JSONB, nullable=True)

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=text("now()"),
    )
