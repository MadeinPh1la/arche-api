# src/stacklion_api/application/schemas/dto/edgar.py
# Copyright (c) Stacklion.
# SPDX-License-Identifier: MIT
"""
Application DTOs for EDGAR filings and statement versions.

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


__all__ = [
    "EdgarFilingDTO",
    "EdgarFilingListDTO",
    "NormalizedStatementPayloadDTO",
    "EdgarStatementVersionDTO",
    "EdgarStatementVersionListDTO",
]
