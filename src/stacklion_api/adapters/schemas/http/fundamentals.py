# src/stacklion_api/adapters/schemas/http/fundamentals.py
# Copyright (c)
# SPDX-License-Identifier: MIT
"""HTTP Schemas: Fundamentals time series and restatement deltas.

Purpose:
    Define HTTP-facing schemas for:
        * Fundamentals time-series points, suitable for panel-friendly
          analytics and backtests.
        * Derived metrics time-series points (margins, growth, returns, etc.).
        * Restatement deltas computed from normalized EDGAR payloads.
        * A normalized-statement view combining the latest version and its
          version history.

Design:
    * Strict Pydantic models with extra="forbid".
    * Field names and types follow API_STANDARDS (snake_case, decimal strings
      for numeric values on the wire, ISO dates). See API_STANDARDS.md.
    * These schemas are transport-facing projections of application/domain
      DTOs and entities:
        - FundamentalsTimeSeriesPoint (domain)
        - DerivedMetricsTimeSeriesPoint (domain)
        - RestatementDelta (domain)
        - NormalizedStatementResult (application)

Layer:
    adapters/schemas/http
"""

from __future__ import annotations

from collections.abc import Mapping
from datetime import date

from pydantic import ConfigDict, Field

from stacklion_api.adapters.schemas.http.base import BaseHTTPSchema
from stacklion_api.adapters.schemas.http.edgar_schemas import (
    EdgarStatementVersionHTTP,
)
from stacklion_api.adapters.schemas.http.edgar_schemas import (
    RestatementDeltaHTTP as RestatementDeltaHTTP,
)
from stacklion_api.domain.enums.edgar import AccountingStandard, FiscalPeriod, StatementType


class FundamentalsTimeSeriesPointHTTP(BaseHTTPSchema):
    """HTTP schema for a single fundamentals time-series point.

    This schema represents the modeling-friendly view of a normalized EDGAR
    statement period, ready for panel/time-series analytics.

    Attributes:
        cik:
            Central Index Key for the filer.
        statement_type:
            Statement type (income, balance sheet, cash flow, etc.).
        accounting_standard:
            Accounting standard (e.g., US_GAAP, IFRS).
        statement_date:
            Reporting period end date.
        fiscal_year:
            Fiscal year associated with the statement (>= 1).
        fiscal_period:
            Fiscal period within the year (e.g., FY, Q1, Q2).
        currency:
            ISO 4217 currency code (e.g., "USD").
        metrics:
            Mapping from canonical metric codes (e.g., "REVENUE") to decimal
            string values (e.g., "383285000000"). Only metrics actually present
            in the underlying normalized payload are included.
        normalized_payload_version_sequence:
            Version sequence of the canonical normalized payload used to build
            this point. This can be used by clients to reason about
            restatements over time.
    """

    model_config = ConfigDict(
        title="FundamentalsTimeSeriesPointHTTP",
        extra="forbid",
        json_schema_extra={
            "examples": [
                {
                    "cik": "0000320193",
                    "statement_type": "INCOME_STATEMENT",
                    "accounting_standard": "US_GAAP",
                    "statement_date": "2024-09-28",
                    "fiscal_year": 2024,
                    "fiscal_period": "FY",
                    "currency": "USD",
                    "metrics": {
                        "REVENUE": "383285000000",
                        "NET_INCOME": "96995000000",
                    },
                    "normalized_payload_version_sequence": 5,
                }
            ],
        },
    )

    cik: str = Field(..., description="Central Index Key for the filer.")
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
        description="Reporting period end date for this time-series point.",
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
    currency: str = Field(
        ...,
        description="ISO 4217 currency code for all monetary metrics (e.g., USD).",
    )
    metrics: Mapping[str, str] = Field(
        default_factory=dict,
        description=(
            "Mapping of canonical metric codes (e.g., REVENUE) to decimal "
            "string values. Only metrics present in the underlying normalized "
            "payload are included."
        ),
    )
    normalized_payload_version_sequence: int = Field(
        ...,
        ge=1,
        description=(
            "Version sequence of the underlying canonical normalized payload "
            "used to derive this time-series point."
        ),
    )


class DerivedMetricsTimeSeriesPointHTTP(BaseHTTPSchema):
    """HTTP schema for a single derived metrics time-series point.

    This schema represents a modeling-friendly view of derived analytics
    (margins, growth rates, cash-flow measures, returns) computed from
    canonical normalized EDGAR payloads.

    Attributes:
        cik:
            Central Index Key for the filer.
        statement_type:
            Statement type that served as the primary source (e.g., income
            statement, balance sheet).
        accounting_standard:
            Accounting standard (e.g., US_GAAP, IFRS).
        statement_date:
            Reporting period end date.
        fiscal_year:
            Fiscal year associated with the statement (>= 1).
        fiscal_period:
            Fiscal period within the year (e.g., FY, Q1, Q2).
        currency:
            ISO 4217 currency code (e.g., "USD").
        metrics:
            Mapping from derived metric codes (e.g., "GROSS_MARGIN") to
            decimal string values.
        normalized_payload_version_sequence:
            Version sequence of the canonical normalized payload used as the
            basis for the derived metrics.
    """

    model_config = ConfigDict(
        title="DerivedMetricsTimeSeriesPointHTTP",
        extra="forbid",
    )

    cik: str = Field(..., description="Central Index Key for the filer.")
    statement_type: StatementType = Field(
        ...,
        description="Primary statement type used for derived metrics.",
    )
    accounting_standard: AccountingStandard = Field(
        ...,
        description="Accounting standard (e.g., US_GAAP, IFRS).",
    )
    statement_date: date = Field(
        ...,
        description="Reporting period end date for this derived-metrics point.",
    )
    fiscal_year: int = Field(
        ...,
        ge=1,
        description="Fiscal year associated with the underlying statement (e.g., 2024).",
    )
    fiscal_period: FiscalPeriod = Field(
        ...,
        description="Fiscal period within the year (e.g., Q1, Q2, FY).",
    )
    currency: str = Field(
        ...,
        description="ISO 4217 currency code for derived monetary metrics (e.g., USD).",
    )
    metrics: Mapping[str, str] = Field(
        default_factory=dict,
        description=(
            "Mapping of derived metric codes (e.g., GROSS_MARGIN) to decimal "
            "string values. Only successfully computed metrics are included."
        ),
    )
    normalized_payload_version_sequence: int = Field(
        ...,
        ge=1,
        description=(
            "Version sequence of the canonical normalized payload used to "
            "compute this derived metrics point."
        ),
    )


class RestatementMetricDeltaHTTP(BaseHTTPSchema):
    """HTTP schema for a single metric-level restatement delta.

    Attributes:
        metric:
            Canonical metric code (e.g., 'REVENUE', 'NET_INCOME').
        old:
            Decimal string value from the 'from' version, or null if
            unavailable.
        new:
            Decimal string value from the 'to' version, or null if
            unavailable.
        diff:
            Decimal string representing new - old, or null if either side was
            unavailable.
    """

    model_config = ConfigDict(
        title="RestatementMetricDeltaHTTP",
        extra="forbid",
    )

    metric: str = Field(
        ...,
        description="Canonical metric code (e.g., REVENUE, NET_INCOME).",
    )
    old: str | None = Field(
        default=None,
        description="Metric value in the 'from' version as a decimal string.",
    )
    new: str | None = Field(
        default=None,
        description="Metric value in the 'to' version as a decimal string.",
    )
    diff: str | None = Field(
        default=None,
        description="Difference new - old as a decimal string, when applicable.",
    )


class NormalizedStatementViewHTTP(BaseHTTPSchema):
    """HTTP schema for a normalized statement view with version history.

    Attributes:
        latest:
            Latest statement version for the requested identity tuple,
            including its normalized payload if available.
        version_history:
            Optional version history ordered by (version_sequence ASC,
            statement_version_id ASC). May be an empty list when version
            history is disabled at the request level.
    """

    model_config = ConfigDict(
        title="NormalizedStatementViewHTTP",
        extra="forbid",
    )

    latest: EdgarStatementVersionHTTP = Field(
        ...,
        description=(
            "Latest statement version for the requested identity tuple, "
            "including normalized payload when available."
        ),
    )
    version_history: list[EdgarStatementVersionHTTP] = Field(
        default_factory=list,
        description=(
            "Version history for the statement identity tuple, ordered by "
            "(version_sequence ASC, statement_version_id ASC)."
        ),
    )


__all__ = [
    "FundamentalsTimeSeriesPointHTTP",
    "DerivedMetricsTimeSeriesPointHTTP",
    "RestatementMetricDeltaHTTP",
    "RestatementDeltaHTTP",
    "NormalizedStatementViewHTTP",
]
