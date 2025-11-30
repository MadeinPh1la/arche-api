# src/stacklion_api/application/schemas/dto/edgar.py
# Copyright (c)
# SPDX-License-Identifier: MIT
"""Application DTOs for EDGAR filings and statement versions.

Purpose:
    Provide strict Pydantic DTOs used by application-layer use cases and
    adapters for EDGAR-related read models. These DTOs are transport-agnostic
    and suitable for mapping into HTTP envelopes defined by API_STANDARDS.

Layer:
    application/schemas/dto
"""

from __future__ import annotations

from datetime import date, datetime

from pydantic import ConfigDict

from stacklion_api.application.schemas.dto.base import BaseDTO
from stacklion_api.domain.enums.edgar import (
    AccountingStandard,
    FilingType,
    FiscalPeriod,
    StatementType,
)


class EdgarFilingDTO(BaseDTO):
    """Normalized EDGAR filing metadata DTO.

    Attributes:
        accession_id: EDGAR accession identifier (e.g., "0000123456-24-000001").
        cik: Central Index Key string for the filer.
        company_name: Legal name of the company, if known.
        filing_type: Filing type enumeration (e.g., 10-K, 10-Q).
        filing_date: Filing date as of EDGAR metadata.
        period_end_date: Reporting period end date, if provided.
        is_amendment: Whether this filing is an amendment (e.g., 10-K/A).
        amendment_sequence: Optional amendment sequence number, if tracked.
        primary_document: Primary document filename, if known.
        accepted_at: Optional acceptance timestamp from EDGAR, if available.
    """

    model_config = ConfigDict(extra="forbid")

    accession_id: str
    cik: str
    company_name: str | None
    filing_type: FilingType
    filing_date: date
    period_end_date: date | None
    is_amendment: bool
    amendment_sequence: int | None = None
    primary_document: str | None = None
    accepted_at: datetime | None = None


class EdgarFilingListDTO(BaseDTO):
    """DTO representing a batch of EDGAR filings."""

    model_config = ConfigDict(extra="forbid")

    items: list[EdgarFilingDTO]


class NormalizedStatementPayloadDTO(BaseDTO):
    """DTO for a canonical normalized financial statement payload.

    This mirrors the CanonicalStatementPayload domain value object but uses
    wire-friendly representations (e.g., strings for decimal values and
    string keys for canonical metrics).

    Attributes:
        cik: Company CIK associated with this statement.
        statement_type: Statement type (income, balance sheet, cash flow, etc.).
        accounting_standard: Accounting standard (e.g., US_GAAP, IFRS).
        statement_date: Reporting period end date.
        fiscal_year: Fiscal year associated with the statement.
        fiscal_period: Fiscal period (e.g., FY, Q1, Q2).
        currency: ISO currency code (e.g., "USD").
        unit_multiplier: Scaling factor; for normalized payloads this MUST be 0.
        core_metrics: Mapping from canonical metric identifiers (strings) to
            stringified numeric values (full units) suitable for JSON.
        extra_metrics: Mapping for long-tail or company-specific metrics.
        dimensions: Simple dimensional context tags (e.g. consolidation).
        source_accession_id: Originating EDGAR accession ID.
        source_taxonomy: Taxonomy identifier (e.g., "US_GAAP_2024").
        source_version_sequence: StatementVersion sequence number this payload
            was derived from.
    """

    model_config = ConfigDict(extra="forbid")

    cik: str
    statement_type: StatementType
    accounting_standard: AccountingStandard
    statement_date: date
    fiscal_year: int
    fiscal_period: FiscalPeriod
    currency: str
    unit_multiplier: int

    core_metrics: dict[str, str]
    extra_metrics: dict[str, str]
    dimensions: dict[str, str]

    source_accession_id: str
    source_taxonomy: str
    source_version_sequence: int


class EdgarStatementVersionDTO(BaseDTO):
    """DTO for a normalized EDGAR statement version.

    Attributes:
        accession_id: Accession ID for the filing that produced this version.
        cik: Company CIK.
        company_name: Legal company name, if known.
        statement_type: Statement type (income, balance sheet, cash flow, etc.).
        accounting_standard: Accounting standard used (e.g., US GAAP).
        statement_date: Statement period end date.
        fiscal_year: Fiscal year associated with the statement.
        fiscal_period: Fiscal period (e.g., FY, Q1, Q2).
        currency: ISO currency code for reported values (e.g., USD).
        is_restated: Whether this version is a restatement.
        restatement_reason: Optional reason for restatement.
        version_source: Provenance of this version (e.g., EDGAR_METADATA_ONLY).
        version_sequence: Monotonic sequence number for the version.
        filing_type: Filing type (e.g., 10-K, 10-Q).
        filing_date: Filing date of the underlying filing.
        accepted_at: Optional EDGAR acceptance timestamp.
        normalized_payload: Optional canonical normalized payload attached to
            this version. May be None for metadata-only or pre-E6-F rows.
        normalized_payload_version: Version identifier for the normalized
            payload schema (e.g., "v1").
    """

    model_config = ConfigDict(extra="forbid")

    accession_id: str
    cik: str
    company_name: str | None
    statement_type: StatementType
    accounting_standard: AccountingStandard
    statement_date: date
    fiscal_year: int
    fiscal_period: FiscalPeriod
    currency: str
    is_restated: bool
    restatement_reason: str | None = None
    version_source: str
    version_sequence: int
    filing_type: FilingType
    filing_date: date
    accepted_at: datetime | None = None

    normalized_payload: NormalizedStatementPayloadDTO | None = None
    normalized_payload_version: str | None = None


class EdgarStatementVersionListDTO(BaseDTO):
    """DTO representing a batch of EDGAR statement versions."""

    model_config = ConfigDict(extra="forbid")

    items: list[EdgarStatementVersionDTO]


class GetNormalizedStatementResultDTO(BaseDTO):
    """Result DTO for a normalized EDGAR statement lookup.

    This is the application-layer result for the "get normalized statement"
    use case. It represents the latest statement version for a given
    (cik, statement_type, fiscal_year, fiscal_period) tuple, along with an
    ordered version history for the same key.

    Attributes:
        cik: Company CIK.
        statement_type: Statement type requested.
        fiscal_year: Fiscal year requested.
        fiscal_period: Fiscal period requested.
        latest_version: Latest statement version matching the criteria.
        version_history: Ordered list of historical versions for the same key.
            Implementations SHOULD ensure this is sorted by version_sequence.
    """

    model_config = ConfigDict(extra="forbid")

    cik: str
    statement_type: StatementType
    fiscal_year: int
    fiscal_period: FiscalPeriod
    latest_version: EdgarStatementVersionDTO
    version_history: list[EdgarStatementVersionDTO]


class RestatementMetricDeltaDTO(BaseDTO):
    """DTO representing the restatement delta for a single metric.

    Attributes:
        metric: Canonical metric identifier.
        old_value: Stringified numeric value from the `from` version, or None
            if the metric did not exist in that version.
        new_value: Stringified numeric value from the `to` version, or None if
            the metric is no longer present.
        diff: Stringified numeric difference (new - old), or None if the
            difference is not computable.
    """

    model_config = ConfigDict(extra="forbid")

    metric: str
    old_value: str | None
    new_value: str | None
    diff: str | None


class RestatementSummaryDTO(BaseDTO):
    """High-level summary DTO for a restatement delta computation.

    Attributes:
        total_metrics_compared: Total number of metrics considered.
        total_metrics_changed: Number of metrics whose value changed.
        has_material_change: Whether the restatement is considered material
            according to application-defined thresholds.
    """

    model_config = ConfigDict(extra="forbid")

    total_metrics_compared: int
    total_metrics_changed: int
    has_material_change: bool


class ComputeRestatementDeltaResultDTO(BaseDTO):
    """Result DTO for EDGAR restatement delta computations.

    Attributes:
        cik: Company CIK.
        statement_type: Statement type.
        fiscal_year: Fiscal year.
        fiscal_period: Fiscal period.
        from_version_sequence: Lower-bound version sequence (inclusive).
        to_version_sequence: Upper-bound version sequence (inclusive).
        summary: High-level summary for the restatement.
        deltas: Per-metric restatement deltas.
    """

    model_config = ConfigDict(extra="forbid")

    cik: str
    statement_type: StatementType
    fiscal_year: int
    fiscal_period: FiscalPeriod
    from_version_sequence: int
    to_version_sequence: int
    summary: RestatementSummaryDTO
    deltas: list[RestatementMetricDeltaDTO]


class RestatementLedgerEntryDTO(BaseDTO):
    """DTO representing a single hop in a restatement ledger.

    Attributes:
        from_version_sequence:
            Source version sequence for the `from` side of the hop.
        to_version_sequence:
            Source version sequence for the `to` side of the hop.
        summary:
            High-level summary of the restatement between the two versions.
    """

    model_config = ConfigDict(extra="forbid")

    from_version_sequence: int
    to_version_sequence: int
    summary: RestatementSummaryDTO


class RestatementLedgerDTO(BaseDTO):
    """DTO representing the restatement ledger for a single statement identity.

    A ledger is defined for a specific (cik, statement_type, fiscal_year,
    fiscal_period) tuple and consists of ordered adjacent restatement hops:

        v1 → v2
        v2 → v3
        ...

    Attributes:
        cik: Company CIK.
        statement_type: Statement type for the ledger.
        fiscal_year: Fiscal year for the ledger identity.
        fiscal_period: Fiscal period for the ledger identity.
        entries: Ordered list of restatement ledger entries.
    """

    model_config = ConfigDict(extra="forbid")

    cik: str
    statement_type: StatementType
    fiscal_year: int
    fiscal_period: FiscalPeriod
    entries: list[RestatementLedgerEntryDTO]


__all__ = [
    "EdgarFilingDTO",
    "EdgarFilingListDTO",
    "NormalizedStatementPayloadDTO",
    "EdgarStatementVersionDTO",
    "EdgarStatementVersionListDTO",
    "GetNormalizedStatementResultDTO",
    "RestatementMetricDeltaDTO",
    "RestatementSummaryDTO",
    "ComputeRestatementDeltaResultDTO",
    "RestatementLedgerEntryDTO",
    "RestatementLedgerDTO",
]
