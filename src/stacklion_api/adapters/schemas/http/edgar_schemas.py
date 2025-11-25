# Copyright (c) Stacklion.
# SPDX-License-Identifier: MIT
"""HTTP Schemas: EDGAR filings and statement versions.

Purpose:
    Define HTTP-facing schemas for EDGAR filings and normalized statement
    versions. These models are used by routers / presenters to expose
    application-layer DTOs via canonical envelopes:

        * PaginatedEnvelope[EdgarFilingHTTP]
        * PaginatedEnvelope[EdgarStatementVersionSummaryHTTP]
        * SuccessEnvelope[EdgarFilingHTTP]
        * SuccessEnvelope[EdgarStatementVersionListHTTP]

Design:
    * Strict Pydantic models with extra="forbid".
    * Field names and types follow API_STANDARDS.
    * Numeric values are exposed as decimal strings for precision.
    * Long-form normalized payloads are modeled but not populated yet.

Layer:
    adapters/schemas/http
"""

from __future__ import annotations

from datetime import date, datetime

from pydantic import ConfigDict, Field

from stacklion_api.adapters.schemas.http.base import BaseHTTPSchema
from stacklion_api.domain.enums.edgar import (
    AccountingStandard,
    FilingType,
    FiscalPeriod,
    StatementType,
)


class EdgarFilingHTTP(BaseHTTPSchema):
    """HTTP schema for a single EDGAR filing.

    This model is a transport-facing projection of :class:`EdgarFilingDTO` and
    is suitable for direct inclusion in PaginatedEnvelope and SuccessEnvelope.

    Attributes:
        accession_id: EDGAR accession identifier (e.g., "0000320193-24-000012").
        cik: Central Index Key string for the filer.
        company_name: Legal company name, if known.
        filing_type: Filing type enumeration value (e.g., "10-K", "10-Q").
        filing_date: Filing date as published by EDGAR.
        period_end_date: Reporting period end date, if provided.
        is_amendment: Whether this filing is an amendment (e.g., "10-K/A").
        amendment_sequence: Optional amendment sequence number.
        primary_document: Primary document filename, if known.
        accepted_at: Acceptance timestamp from EDGAR, if available.
    """

    model_config = ConfigDict(
        title="EdgarFilingHTTP",
        extra="forbid",
        json_schema_extra={
            "examples": [
                {
                    "accession_id": "0000320193-24-000012",
                    "cik": "0000320193",
                    "company_name": "Apple Inc.",
                    "filing_type": "10-K",
                    "filing_date": "2024-10-25",
                    "period_end_date": "2024-09-28",
                    "is_amendment": False,
                    "amendment_sequence": None,
                    "primary_document": "aapl-20240928.htm",
                    "accepted_at": "2024-10-25T16:05:00",
                }
            ]
        },
    )

    accession_id: str = Field(
        ...,
        description="EDGAR accession identifier (e.g., 0000320193-24-000012).",
    )
    cik: str = Field(..., description="Central Index Key for the filer.")
    company_name: str | None = Field(
        default=None,
        description="Legal name of the company, if known.",
    )
    filing_type: FilingType = Field(
        ...,
        description="Filing type enumeration (e.g., 10-K, 10-Q).",
    )
    filing_date: date = Field(
        ...,
        description="Calendar date when the filing was accepted by the SEC.",
    )
    period_end_date: date | None = Field(
        default=None,
        description="Reporting period end date, when provided by EDGAR.",
    )
    is_amendment: bool = Field(
        ...,
        description="Whether this filing is an amendment to a prior submission.",
    )
    amendment_sequence: int | None = Field(
        default=None,
        description="Amendment sequence number when this is an amendment.",
    )
    primary_document: str | None = Field(
        default=None,
        description="Primary document filename or identifier, if known.",
    )
    accepted_at: datetime | None = Field(
        default=None,
        description="Acceptance timestamp from EDGAR, if available.",
    )


class EdgarStatementVersionSummaryHTTP(BaseHTTPSchema):
    """HTTP summary schema for a statement version.

    This shape is used in company-level listing endpoints where the primary
    concern is metadata and versioning, not full normalized line items.

    Attributes:
        accession_id: EDGAR accession identifier for the backing filing.
        cik: Company CIK.
        company_name: Legal company name, if known.
        statement_type: Statement type (income, balance sheet, cash flow).
        accounting_standard: Accounting standard (e.g., US_GAAP).
        statement_date: Statement period end date.
        fiscal_year: Fiscal year associated with the statement.
        fiscal_period: Fiscal period (e.g., FY, Q1, Q2).
        currency: ISO 4217 currency code.
        is_restated: Whether this version is a restatement.
        restatement_reason: Optional reason for restatement.
        version_source: Provenance of this version.
        version_sequence: Monotonic sequence per (company, type, date).
        filing_type: Filing type (e.g., 10-K, 10-Q).
        filing_date: Filing date of the underlying filing.
    """

    model_config = ConfigDict(
        title="EdgarStatementVersionSummaryHTTP",
        extra="forbid",
    )

    accession_id: str = Field(..., description="EDGAR accession identifier.")
    cik: str = Field(..., description="Central Index Key for the filer.")
    company_name: str | None = Field(
        default=None,
        description="Legal company name, if known.",
    )
    statement_type: StatementType = Field(
        ...,
        description="High-level statement taxonomy (income, balance sheet, cash flow).",
    )
    accounting_standard: AccountingStandard = Field(
        ...,
        description="Accounting standard (e.g., US_GAAP, IFRS).",
    )
    statement_date: date = Field(
        ...,
        description="Reporting period end date for this statement version.",
    )
    fiscal_year: int = Field(
        ...,
        ge=1,
        description="Fiscal year associated with the statement (e.g., 2024).",
    )
    fiscal_period: FiscalPeriod = Field(
        ...,
        description="Fiscal period within the year (e.g., Q1, Q2, FY).",
    )
    currency: str = Field(..., description="ISO 4217 currency code (e.g., USD).")
    is_restated: bool = Field(
        ...,
        description="Whether this statement represents a restatement.",
    )
    restatement_reason: str | None = Field(
        default=None,
        description="Human-readable reason for restatement, when applicable.",
    )
    version_source: str = Field(
        ...,
        description="Short code describing where this version originates.",
    )
    version_sequence: int = Field(
        ...,
        ge=1,
        description="Monotonically increasing version number.",
    )
    filing_type: FilingType = Field(
        ...,
        description="Filing type (e.g., 10-K, 10-Q).",
    )
    filing_date: date = Field(
        ...,
        description="Filing date of the associated EDGAR filing.",
    )


class NormalizedFactHTTP(BaseHTTPSchema):
    """HTTP schema for a normalized financial fact within a statement.

    This schema is forward-looking: E5 exposes the contract, but the
    normalized payload is not yet populated. Numeric values are carried
    as decimal strings to preserve precision for clients.

    Attributes:
        metric: Canonical metric code (e.g., 'REVENUE', 'NET_INCOME').
        label: Human-readable label for the metric, if available.
        unit: Unit code for the value (e.g., 'USD', 'shares').
        period_start: Inclusive period start date, or None for instant metrics.
        period_end: Inclusive period end date.
        value: Decimal string representation of the value.
        dimension: Optional dimensional breakdown (e.g., segment, class).
        source_line_item: Optional original line item label from the filing.
    """

    model_config = ConfigDict(
        title="NormalizedFactHTTP",
        extra="forbid",
    )

    metric: str = Field(
        ...,
        description="Canonical metric code (e.g., REVENUE, NET_INCOME).",
    )
    label: str | None = Field(
        default=None,
        description="Human-readable label for the metric, if available.",
    )
    unit: str = Field(
        ...,
        description="Unit code for the metric (e.g., USD, shares).",
    )
    period_start: date | None = Field(
        default=None,
        description="Inclusive period start date, or null for instant metrics.",
    )
    period_end: date = Field(
        ...,
        description="Inclusive period end date for the metric value.",
    )
    value: str = Field(
        ...,
        description="Value as a decimal string, preserving precision.",
    )
    dimension: dict[str, str] | None = Field(
        default=None,
        description="Optional dimensional breakdown (e.g., segment, class).",
    )
    source_line_item: str | None = Field(
        default=None,
        description="Original line item label from the filing, if known.",
    )


class NormalizedStatementHTTP(BaseHTTPSchema):
    """HTTP schema for a normalized financial statement payload.

    Attributes:
        statement_type: Statement type (income, balance sheet, cash flow).
        accounting_standard: Accounting standard (e.g., US_GAAP).
        fiscal_year: Fiscal year associated with the statement.
        fiscal_period: Fiscal period within the year (e.g., Q1, FY).
        currency: ISO 4217 currency for all monetary values.
        facts: Collection of normalized metric facts.
    """

    model_config = ConfigDict(
        title="NormalizedStatementHTTP",
        extra="forbid",
    )

    statement_type: StatementType = Field(
        ...,
        description="High-level statement taxonomy (income, balance sheet, cash flow).",
    )
    accounting_standard: AccountingStandard = Field(
        ...,
        description="Accounting standard (e.g., US_GAAP, IFRS).",
    )
    fiscal_year: int = Field(
        ...,
        ge=1,
        description="Fiscal year associated with the statement (e.g., 2024).",
    )
    fiscal_period: FiscalPeriod = Field(
        ...,
        description="Fiscal period within the year (e.g., Q1, FY).",
    )
    currency: str = Field(
        ...,
        description="ISO 4217 currency code used for monetary facts.",
    )
    facts: list[NormalizedFactHTTP] = Field(
        default_factory=list,
        description="Normalized financial facts for this statement version.",
    )


class EdgarStatementVersionHTTP(BaseHTTPSchema):
    """HTTP schema for a full statement version (per filing).

    This schema mirrors :class:`EdgarStatementVersionDTO` and adds an
    optional ``normalized_payload`` field for future long-form normalized
    statement data.

    Attributes:
        accession_id: EDGAR accession identifier.
        cik: Company CIK.
        company_name: Legal company name, if known.
        statement_type: Statement type (income, balance sheet, cash flow).
        accounting_standard: Accounting standard (e.g., US_GAAP).
        statement_date: Reporting period end date.
        fiscal_year: Fiscal year.
        fiscal_period: Fiscal period within the year.
        currency: ISO 4217 currency code.
        is_restated: Whether this version is a restatement.
        restatement_reason: Explanation when restated.
        version_source: Provenance of the version.
        version_sequence: Monotonic sequence per (company, type, date).
        filing_type: Filing type (e.g., 10-K, 10-Q).
        filing_date: Filing date.
        normalized_payload: Optional normalized statement payload (future use).
    """

    model_config = ConfigDict(
        title="EdgarStatementVersionHTTP",
        extra="forbid",
    )

    accession_id: str = Field(..., description="EDGAR accession identifier.")
    cik: str = Field(..., description="Central Index Key for the filer.")
    company_name: str | None = Field(
        default=None,
        description="Legal company name, if known.",
    )
    statement_type: StatementType = Field(
        ...,
        description="High-level statement taxonomy (income, balance sheet, cash flow).",
    )
    accounting_standard: AccountingStandard = Field(
        ...,
        description="Accounting standard (e.g., US_GAAP, IFRS).",
    )
    statement_date: date = Field(
        ...,
        description="Reporting period end date for this statement version.",
    )
    fiscal_year: int = Field(
        ...,
        ge=1,
        description="Fiscal year associated with the statement (e.g., 2024).",
    )
    fiscal_period: FiscalPeriod = Field(
        ...,
        description="Fiscal period within the year (e.g., Q1, Q2, FY).",
    )
    currency: str = Field(..., description="ISO 4217 currency code (e.g., USD).")
    is_restated: bool = Field(
        ...,
        description="Whether this statement represents a restatement.",
    )
    restatement_reason: str | None = Field(
        default=None,
        description="Human-readable reason for restatement, if applicable.",
    )
    version_source: str = Field(
        ...,
        description="Short code describing where this version originates.",
    )
    version_sequence: int = Field(
        ...,
        ge=1,
        description="Monotonically increasing version number.",
    )
    filing_type: FilingType = Field(
        ...,
        description="Filing type (e.g., 10-K, 10-Q).",
    )
    filing_date: date = Field(
        ...,
        description="Filing date of the associated EDGAR filing.",
    )
    normalized_payload: NormalizedStatementHTTP | None = Field(
        default=None,
        description=(
            "Optional normalized financial statement payload. "
            "This field is reserved for future use and is currently null."
        ),
    )


class EdgarStatementVersionListHTTP(BaseHTTPSchema):
    """HTTP container for statement versions associated with a single filing.

    Attributes:
        filing: Filing metadata associated with the statement versions.
        items: Collection of statement versions for the filing.
    """

    model_config = ConfigDict(
        title="EdgarStatementVersionListHTTP",
        extra="forbid",
    )

    filing: EdgarFilingHTTP = Field(
        ...,
        description="Filing metadata associated with the statement versions.",
    )
    items: list[EdgarStatementVersionHTTP] = Field(
        default_factory=list,
        description="Statement versions attached to the filing.",
    )


__all__ = [
    "EdgarFilingHTTP",
    "EdgarStatementVersionSummaryHTTP",
    "NormalizedFactHTTP",
    "NormalizedStatementHTTP",
    "EdgarStatementVersionHTTP",
    "EdgarStatementVersionListHTTP",
]
