# src/stacklion_api/adapters/schemas/http/edgar_schemas.py
# Copyright (c)
# SPDX-License-Identifier: MIT
"""HTTP Schemas: EDGAR filings, statements, and normalized facts.

Purpose:
    Define HTTP-facing schemas for EDGAR-related payloads:

        * Normalized facts and statements (analytics-grade, modeling-ready).
        * EDGAR statement versions (with optional normalized payloads).
        * EDGAR filing metadata and statement-version listings.
        * Derived-metrics time series and metric-view catalog.
        * Derived-metrics catalog (introspection of the derived-metrics engine).
        * Restatement deltas and ledgers.

Design:
    * Strict Pydantic models with extra="forbid".
    * Field names and types follow API_STANDARDS:
        - snake_case
        - ISO dates
        - stringified numeric values on the wire where applicable.
    * These are transport-facing projections of domain entities and DTOs:
        - EdgarFiling / EdgarStatementVersion / CanonicalStatementPayload, etc.

Layer:
    adapters/schemas/http
"""

from __future__ import annotations

from datetime import date, datetime

from pydantic import BaseModel, ConfigDict, Field

from stacklion_api.adapters.schemas.http.base import BaseHTTPSchema
from stacklion_api.domain.enums.edgar import (
    AccountingStandard,
    FilingType,
    FiscalPeriod,
    StatementType,
)

# --------------------------------------------------------------------------- #
# Normalized facts and statements (analytics-grade view)                      #
# --------------------------------------------------------------------------- #


class NormalizedFactHTTP(BaseHTTPSchema):
    """HTTP schema for a single normalized fact.

    This is the atomic modeling unit extracted from a normalized EDGAR
    payload. It is intentionally simple and wire-friendly.

    Attributes:
        metric:
            Canonical metric code (e.g., "REVENUE", "NET_INCOME").
        label:
            Human-readable label for the metric, when available.
        unit:
            ISO 4217 currency code or other unit code (e.g., "USD").
        period_start:
            Inclusive start of the fact's reporting period.
        period_end:
            Inclusive end of the fact's reporting period.
        value:
            Stringified numeric value in full units, suitable for JSON.
        dimension:
            Optional simple dimensional context (e.g., {"segment": "US"}).
        source_line_item:
            Original line-item label from the filing, when available.
    """

    model_config = ConfigDict(
        title="NormalizedFactHTTP",
        extra="forbid",
        json_schema_extra={
            "examples": [
                {
                    "metric": "REVENUE",
                    "label": "Revenue",
                    "unit": "USD",
                    "period_start": "2024-01-01",
                    "period_end": "2024-03-31",
                    "value": "123456.78",
                    "dimension": {"segment": "US"},
                    "source_line_item": "Net sales",
                }
            ]
        },
    )

    metric: str = Field(
        ...,
        description="Canonical metric code (e.g., REVENUE, NET_INCOME).",
    )
    label: str | None = Field(
        default=None,
        description="Human-readable label for the metric, when available.",
    )
    unit: str = Field(
        ...,
        description="Unit code for the value (e.g., ISO 4217 currency code such as USD).",
    )
    period_start: date = Field(
        ...,
        description="Inclusive start date of the reporting period.",
    )
    period_end: date = Field(
        ...,
        description="Inclusive end date of the reporting period.",
    )
    value: str = Field(
        ...,
        description="Stringified numeric value in full units suitable for JSON.",
    )
    dimension: dict[str, str] | None = Field(
        default=None,
        description="Optional simple dimensional context (e.g., {'segment': 'US'}).",
    )
    source_line_item: str | None = Field(
        default=None,
        description="Original line-item label from the filing, when available.",
    )


class NormalizedStatementHTTP(BaseHTTPSchema):
    """HTTP schema for a normalized EDGAR statement.

    This is a wire-facing analytics view that groups normalized facts under a
    statement identity. It keeps the required surface small for clients while
    exposing richer metadata when available.

    Attributes:
        statement_type:
            Statement type (income, balance sheet, cash flow, etc.).
        accounting_standard:
            Accounting standard (e.g., US_GAAP, IFRS).
        statement_date:
            Reporting period end date, if known.
        fiscal_year:
            Fiscal year associated with the statement, when available.
        fiscal_period:
            Fiscal period within the year (e.g., FY, Q1, Q2), when available.
        currency:
            ISO 4217 currency code for monetary values (e.g., "USD"), when known.
        cik:
            Central Index Key for the filer, when available.
        unit_multiplier:
            Unit multiplier used when the statement was normalized. For fully
            normalized payloads this SHOULD be 0.
        source_accession_id:
            Originating EDGAR accession identifier, when available.
        source_taxonomy:
            Source taxonomy identifier (e.g., "US_GAAP_2024"), when available.
        source_version_sequence:
            Version sequence from the canonical normalized payload, when tracked.
        facts:
            Collection of normalized facts belonging to this statement.
    """

    model_config = ConfigDict(
        title="NormalizedStatementHTTP",
        extra="forbid",
        json_schema_extra={
            "examples": [
                {
                    "statement_type": "INCOME_STATEMENT",
                    "accounting_standard": "US_GAAP",
                    "statement_date": "2024-03-31",
                    "fiscal_year": 2024,
                    "fiscal_period": "Q1",
                    "currency": "USD",
                    "cik": "0000320193",
                    "unit_multiplier": 0,
                    "source_accession_id": "0000320193-24-000012",
                    "source_taxonomy": "US_GAAP_2024",
                    "source_version_sequence": 3,
                    "facts": [
                        {
                            "metric": "REVENUE",
                            "label": "Revenue",
                            "unit": "USD",
                            "period_start": "2024-01-01",
                            "period_end": "2024-03-31",
                            "value": "123456.78",
                            "dimension": {"segment": "US"},
                            "source_line_item": "Net sales",
                        }
                    ],
                }
            ],
        },
    )

    statement_type: StatementType = Field(
        ...,
        description="High-level statement taxonomy (income, balance sheet, cash flow).",
    )
    accounting_standard: AccountingStandard = Field(
        ...,
        description="Accounting standard (e.g., US_GAAP, IFRS).",
    )
    statement_date: date | None = Field(
        default=None,
        description="Reporting period end date for the statement, when known.",
    )
    fiscal_year: int | None = Field(
        default=None,
        ge=1,
        description="Fiscal year associated with the statement, when available.",
    )
    fiscal_period: FiscalPeriod | None = Field(
        default=None,
        description="Fiscal period within the year (e.g., Q1, Q2, FY), when available.",
    )
    currency: str | None = Field(
        default=None,
        description="ISO 4217 currency code for monetary values (e.g., USD), when known.",
    )
    cik: str | None = Field(
        default=None,
        description="Central Index Key for the filer, if known.",
    )
    unit_multiplier: int = Field(
        default=0,
        description=(
            "Unit multiplier applied when the statement was normalized. "
            "Normalized canonical payloads should typically use 0."
        ),
    )
    source_accession_id: str | None = Field(
        default=None,
        description="Originating EDGAR accession identifier, when available.",
    )
    source_taxonomy: str | None = Field(
        default=None,
        description="Source taxonomy identifier (e.g., 'US_GAAP_2024'), when available.",
    )
    source_version_sequence: int | None = Field(
        default=None,
        description="Version sequence of the canonical normalized payload, when tracked.",
    )
    facts: list[NormalizedFactHTTP] = Field(
        default_factory=list,
        description="Collection of normalized facts belonging to this statement.",
    )


# --------------------------------------------------------------------------- #
# Filing metadata                                                             #
# --------------------------------------------------------------------------- #


class EdgarFilingHTTP(BaseHTTPSchema):
    """HTTP schema for normalized EDGAR filing metadata.

    Mirrors :class:`EdgarFilingDTO` at the application layer but is
    transport-facing and API_STANDARDS-compliant.
    """

    model_config = ConfigDict(
        title="EdgarFilingHTTP",
        extra="forbid",
    )

    accession_id: str = Field(
        ...,
        description="EDGAR accession identifier (e.g., '0000123456-24-000001').",
    )
    cik: str = Field(
        ...,
        description="Central Index Key string for the filer.",
    )
    company_name: str | None = Field(
        default=None,
        description="Legal company name for the filer, when known.",
    )
    filing_type: FilingType = Field(
        ...,
        description="Normalized filing type (e.g., FORM_10_K, FORM_10_Q).",
    )
    filing_date: date = Field(
        ...,
        description="Filing date as recorded by EDGAR.",
    )
    period_end_date: date | None = Field(
        default=None,
        description="Reporting period end date, if provided.",
    )
    is_amendment: bool = Field(
        ...,
        description="Whether this filing represents an amendment (e.g., 10-K/A).",
    )
    amendment_sequence: int | None = Field(
        default=None,
        description="Optional amendment sequence number, when tracked.",
    )
    primary_document: str | None = Field(
        default=None,
        description="Primary document filename for the filing, when known.",
    )
    accepted_at: datetime | None = Field(
        default=None,
        description="Optional EDGAR acceptance timestamp, when available.",
    )


# --------------------------------------------------------------------------- #
# Statement versions (metadata + normalized payloads)                         #
# --------------------------------------------------------------------------- #


class EdgarStatementVersionSummaryHTTP(BaseHTTPSchema):
    """HTTP schema for a summary view of an EDGAR statement version.

    Used for lightweight listings where the full normalized payload is not
    required, but we still want restatement provenance.
    """

    model_config = ConfigDict(
        title="EdgarStatementVersionSummaryHTTP",
        extra="forbid",
    )

    accession_id: str = Field(
        ...,
        description="EDGAR accession identifier for the filing that produced this version.",
    )
    cik: str = Field(
        ...,
        description="Central Index Key string for the filer.",
    )
    company_name: str | None = Field(
        default=None,
        description="Legal company name for the filer, when available.",
    )
    statement_type: StatementType = Field(
        ...,
        description="High-level statement taxonomy (income, balance sheet, cash flow).",
    )
    accounting_standard: AccountingStandard = Field(
        ...,
        description="Accounting standard used (e.g., US_GAAP, IFRS).",
    )
    statement_date: date = Field(
        ...,
        description="Statement period end date.",
    )
    fiscal_year: int = Field(
        ...,
        ge=1,
        description="Fiscal year associated with the statement.",
    )
    fiscal_period: FiscalPeriod = Field(
        ...,
        description="Fiscal period within the year (e.g., Q1, Q2, FY).",
    )
    currency: str = Field(
        ...,
        description="ISO 4217 currency code for reported values (e.g., USD).",
    )
    is_restated: bool = Field(
        ...,
        description="Whether this version represents a restatement.",
    )
    restatement_reason: str | None = Field(
        default=None,
        description="Optional reason for restatement, when supplied.",
    )
    version_sequence: int = Field(
        ...,
        ge=1,
        description="Monotonic sequence number for the version.",
    )
    version_source: str = Field(
        ...,
        description="Provenance of this version (e.g., 'EDGAR_METADATA_ONLY').",
    )
    filing_type: FilingType = Field(
        ...,
        description="Filing type (e.g., FORM_10_K, FORM_10_Q).",
    )
    filing_date: date = Field(
        ...,
        description="Filing date of the underlying filing.",
    )


class EdgarStatementVersionHTTP(BaseHTTPSchema):
    """HTTP schema for a full EDGAR statement version with optional payload."""

    model_config = ConfigDict(
        title="EdgarStatementVersionHTTP",
        extra="forbid",
    )

    accession_id: str = Field(
        ...,
        description="EDGAR accession identifier for the filing that produced this version.",
    )
    cik: str = Field(
        ...,
        description="Central Index Key string for the filer.",
    )
    company_name: str | None = Field(
        default=None,
        description="Legal company name for the filer, when available.",
    )
    statement_type: StatementType = Field(
        ...,
        description="High-level statement taxonomy (income, balance sheet, cash flow).",
    )
    accounting_standard: AccountingStandard = Field(
        ...,
        description="Accounting standard used (e.g., US_GAAP, IFRS).",
    )
    statement_date: date = Field(
        ...,
        description="Statement period end date.",
    )
    fiscal_year: int = Field(
        ...,
        ge=1,
        description="Fiscal year associated with the statement.",
    )
    fiscal_period: FiscalPeriod = Field(
        ...,
        description="Fiscal period within the year (e.g., Q1, Q2, FY).",
    )
    currency: str = Field(
        ...,
        description="ISO 4217 currency code for reported values (e.g., USD).",
    )
    is_restated: bool = Field(
        ...,
        description="Whether this version represents a restatement.",
    )
    restatement_reason: str | None = Field(
        default=None,
        description="Optional reason for restatement, when supplied.",
    )
    version_source: str = Field(
        ...,
        description="Provenance of this version (e.g., 'EDGAR_METADATA_ONLY').",
    )
    version_sequence: int = Field(
        ...,
        ge=1,
        description="Monotonic sequence number for the version.",
    )
    filing_type: FilingType = Field(
        ...,
        description="Filing type (e.g., FORM_10_K, FORM_10_Q).",
    )
    filing_date: date = Field(
        ...,
        description="Filing date of the underlying filing.",
    )
    accepted_at: datetime | None = Field(
        default=None,
        description="EDGAR acceptance timestamp, when available.",
    )
    normalized_payload: NormalizedStatementHTTP | None = Field(
        default=None,
        description=(
            "Optional normalized statement payload attached to this version. "
            "May be None for metadata-only or pre-normalization rows."
        ),
    )
    normalized_payload_version: str | None = Field(
        default=None,
        description="Version identifier for the normalized payload schema (e.g., 'v1').",
    )


class EdgarStatementVersionListHTTP(BaseHTTPSchema):
    """HTTP schema for a list of EDGAR statement versions.

    This is a thin wrapper around a collection of full statement-version
    representations. Pagination is handled by the standard PaginatedEnvelope
    contract.
    """

    model_config = ConfigDict(
        title="EdgarStatementVersionListHTTP",
        extra="forbid",
    )

    filing: EdgarFilingHTTP | None = Field(
        default=None,
        description=(
            "Optional filing metadata shared across all versions when listing "
            "versions for a single filing."
        ),
    )
    items: list[EdgarStatementVersionHTTP] = Field(
        default_factory=list,
        description="Collection of full statement-version records.",
    )


# --------------------------------------------------------------------------- #
# Derived metrics time series                                                 #
# --------------------------------------------------------------------------- #


class EdgarDerivedMetricsPointHTTP(BaseModel):
    """HTTP schema for a single derived metrics time-series point.

    This mirrors the application-layer EdgarDerivedMetricsPointDTO but
    exposes metrics as a mapping from metric *codes* (strings) to
    decimal-string values for wire stability.
    """

    model_config = ConfigDict(extra="forbid")

    cik: str
    statement_type: StatementType
    accounting_standard: AccountingStandard
    statement_date: date
    fiscal_year: int
    fiscal_period: FiscalPeriod
    currency: str
    metrics: dict[str, str]
    normalized_payload_version_sequence: int


class EdgarDerivedMetricsTimeSeriesHTTP(BaseModel):
    """HTTP schema for a derived metrics time series.

    Attributes:
        ciks:
            Normalized list of company CIKs included in the series.
        statement_type:
            Primary statement type used as the base for the derived metrics.
        frequency:
            Time-series frequency ("annual" or "quarterly").
        from_date:
            Inclusive lower bound on statement_date.
        to_date:
            Inclusive upper bound on statement_date.
        points:
            Derived metrics time-series points in deterministic order.
        view:
            Optional metric view (bundle) identifier when the series is
            produced via a named view. Null for ad-hoc metric selections.
    """

    model_config = ConfigDict(extra="forbid")

    ciks: list[str]
    statement_type: StatementType
    frequency: str
    from_date: date
    to_date: date
    points: list[EdgarDerivedMetricsPointHTTP]
    view: str | None = Field(
        default=None,
        description=(
            "Metric view (bundle) identifier when the series is derived from a "
            "named view; null for ad-hoc metric selections."
        ),
    )


# --------------------------------------------------------------------------- #
# Derived metrics catalog                                                     #
# --------------------------------------------------------------------------- #


class EdgarDerivedMetricSpecHTTP(BaseHTTPSchema):
    """HTTP schema for a single derived metric specification.

    This exposes the public-facing contract for a derived metric as defined
    in the derived-metrics engine registry, without leaking internal types.
    """

    model_config = ConfigDict(
        title="EdgarDerivedMetricSpecHTTP",
        extra="forbid",
    )

    code: str = Field(
        ...,
        description="Derived metric code, matching the DerivedMetric enum value.",
    )
    category: str = Field(
        ...,
        description="High-level category for the metric (e.g., MARGIN, GROWTH).",
    )
    description: str = Field(
        ...,
        description="Short human-readable description of the metric definition.",
    )
    is_experimental: bool = Field(
        ...,
        description="Whether this metric is considered experimental.",
    )
    required_statement_types: list[StatementType] = Field(
        default_factory=list,
        description=(
            "Statement types for which this metric is conceptually valid "
            "(e.g., INCOME_STATEMENT, BALANCE_SHEET)."
        ),
    )
    required_inputs: list[str] = Field(
        default_factory=list,
        description=(
            "Canonical input metric codes required to compute this metric, "
            "expressed as string identifiers."
        ),
    )
    uses_history: bool = Field(
        ...,
        description="Whether the metric inspects prior-period history.",
    )
    window_requirements: dict[str, int] = Field(
        default_factory=dict,
        description=(
            "History window requirements keyed by requirement name, such as "
            '{"history_periods": 7} for TTM metrics.'
        ),
    )


class EdgarDerivedMetricsCatalogHTTP(BaseHTTPSchema):
    """HTTP schema for the catalog of registered derived metrics."""

    model_config = ConfigDict(
        title="EdgarDerivedMetricsCatalogHTTP",
        extra="forbid",
    )

    metrics: list[EdgarDerivedMetricSpecHTTP] = Field(
        default_factory=list,
        description="Collection of all registered derived metrics.",
    )


# --------------------------------------------------------------------------- #
# Metric views catalog                                                        #
# --------------------------------------------------------------------------- #


class MetricViewHTTP(BaseHTTPSchema):
    """HTTP schema for a single metric view (bundle) definition."""

    model_config = ConfigDict(
        title="MetricViewHTTP",
        extra="forbid",
    )

    code: str = Field(
        ...,
        description="Metric view (bundle) code, e.g. 'core_fundamentals'.",
    )
    label: str = Field(
        ...,
        description="Short human-readable label for the view.",
    )
    description: str = Field(
        ...,
        description="Longer description of the view's intent and use-cases.",
    )
    metrics: list[str] = Field(
        ...,
        description="Ordered list of derived metric codes belonging to this view.",
    )


class MetricViewsCatalogHTTP(BaseHTTPSchema):
    """HTTP schema for the catalog of registered metric views."""

    model_config = ConfigDict(
        title="MetricViewsCatalogHTTP",
        extra="forbid",
    )

    views: list[MetricViewHTTP] = Field(
        default_factory=list,
        description="Collection of all registered metric views.",
    )


# --------------------------------------------------------------------------- #
# Restatement deltas and ledger                                               #
# --------------------------------------------------------------------------- #


class RestatementMetricDeltaHTTP(BaseHTTPSchema):
    """HTTP schema for a single restatement metric delta."""

    model_config = ConfigDict(
        title="RestatementMetricDeltaHTTP",
        extra="forbid",
    )

    metric: str = Field(
        ...,
        description="Canonical metric code (e.g., REVENUE, EPS_DILUTED).",
    )
    old_value: str | None = Field(
        default=None,
        description=(
            "Stringified numeric value from the 'from' version, or null if the "
            "metric did not exist in that version."
        ),
    )
    new_value: str | None = Field(
        default=None,
        description=(
            "Stringified numeric value from the 'to' version, or null if the "
            "metric is no longer present."
        ),
    )
    diff: str | None = Field(
        default=None,
        description=("Stringified numeric difference (new - old), or null if not " "computable."),
    )


class RestatementSummaryHTTP(BaseHTTPSchema):
    """HTTP schema for a high-level restatement summary."""

    model_config = ConfigDict(
        title="RestatementSummaryHTTP",
        extra="forbid",
    )

    total_metrics_compared: int = Field(
        ...,
        description="Total number of metrics considered in the restatement.",
    )
    total_metrics_changed: int = Field(
        ...,
        description="Number of metrics whose value changed between versions.",
    )
    has_material_change: bool = Field(
        ...,
        description=(
            "Whether the restatement is considered material under "
            "application-defined thresholds."
        ),
    )


class RestatementDeltaHTTP(BaseHTTPSchema):
    """HTTP schema for a restatement delta between two statement versions."""

    model_config = ConfigDict(
        title="RestatementDeltaHTTP",
        extra="forbid",
    )

    cik: str = Field(
        ...,
        description="Company CIK for the statement identity.",
    )
    statement_type: StatementType = Field(
        ...,
        description="Statement type for the restatement (e.g., INCOME_STATEMENT).",
    )
    fiscal_year: int = Field(
        ...,
        ge=1,
        description="Fiscal year for the statement identity.",
    )
    fiscal_period: FiscalPeriod = Field(
        ...,
        description="Fiscal period for the statement identity (e.g., FY, Q1).",
    )
    from_version_sequence: int = Field(
        ...,
        ge=1,
        description="Lower-bound version sequence (inclusive).",
    )
    to_version_sequence: int = Field(
        ...,
        ge=1,
        description="Upper-bound version sequence (inclusive).",
    )
    summary: RestatementSummaryHTTP = Field(
        ...,
        description="High-level summary of the restatement.",
    )
    deltas: list[RestatementMetricDeltaHTTP] = Field(
        default_factory=list,
        description="Per-metric restatement deltas for the hop.",
    )


class RestatementLedgerEntryHTTP(BaseHTTPSchema):
    """HTTP schema for a single hop in a restatement ledger."""

    model_config = ConfigDict(
        title="RestatementLedgerEntryHTTP",
        extra="forbid",
    )

    cik: str = Field(
        ...,
        description="Company CIK for the statement identity.",
    )
    statement_type: StatementType = Field(
        ...,
        description="Statement type for the ledger.",
    )
    fiscal_year: int = Field(
        ...,
        ge=1,
        description="Fiscal year for the ledger identity.",
    )
    fiscal_period: FiscalPeriod = Field(
        ...,
        description="Fiscal period for the ledger identity.",
    )
    from_version_sequence: int = Field(
        ...,
        ge=1,
        description="Source version sequence for the 'from' side of the hop.",
    )
    to_version_sequence: int = Field(
        ...,
        ge=1,
        description="Source version sequence for the 'to' side of the hop.",
    )
    summary: RestatementSummaryHTTP = Field(
        ...,
        description="High-level summary of the restatement between the versions.",
    )
    deltas: list[RestatementMetricDeltaHTTP] = Field(
        default_factory=list,
        description="Per-metric restatement deltas for this hop, when available.",
    )


class RestatementLedgerHTTP(BaseHTTPSchema):
    """HTTP schema for a restatement ledger over a statement version history."""

    model_config = ConfigDict(
        title="RestatementLedgerHTTP",
        extra="forbid",
    )

    cik: str = Field(
        ...,
        description="Company CIK for the statement identity.",
    )
    statement_type: StatementType = Field(
        ...,
        description="Statement type for the ledger.",
    )
    fiscal_year: int = Field(
        ...,
        ge=1,
        description="Fiscal year for the ledger identity.",
    )
    fiscal_period: FiscalPeriod = Field(
        ...,
        description="Fiscal period for the ledger identity.",
    )
    total_hops: int = Field(
        ...,
        ge=0,
        description="Total number of restatement hops in the ledger.",
    )
    entries: list[RestatementLedgerEntryHTTP] = Field(
        default_factory=list,
        description="Ordered list of restatement ledger entries.",
    )


__all__ = [
    "EdgarFilingHTTP",
    "EdgarStatementVersionSummaryHTTP",
    "EdgarStatementVersionHTTP",
    "EdgarStatementVersionListHTTP",
    "NormalizedStatementHTTP",
    "NormalizedFactHTTP",
    "EdgarDerivedMetricsPointHTTP",
    "EdgarDerivedMetricsTimeSeriesHTTP",
    "EdgarDerivedMetricSpecHTTP",
    "EdgarDerivedMetricsCatalogHTTP",
    "MetricViewHTTP",
    "MetricViewsCatalogHTTP",
    "RestatementMetricDeltaHTTP",
    "RestatementSummaryHTTP",
    "RestatementDeltaHTTP",
    "RestatementLedgerEntryHTTP",
    "RestatementLedgerHTTP",
]
