# src/stacklion_api/adapters/schemas/http/edgar_dq_schemas.py
# Copyright (c)
# SPDX-License-Identifier: MIT
"""HTTP Schemas: EDGAR Data Quality (DQ) & Fact Store."""

from __future__ import annotations

from datetime import date, datetime

from pydantic import BaseModel, ConfigDict, Field

from stacklion_api.domain.enums.edgar import MaterialityClass


class NormalizedFactHTTP(BaseModel):
    """HTTP projection of NormalizedFactDTO."""

    model_config = ConfigDict(extra="forbid")

    cik: str = Field(..., description="Company CIK (zero-padded string).")
    statement_type: str = Field(
        ...,
        description="Statement type (e.g. INCOME_STATEMENT, BALANCE_SHEET).",
    )
    accounting_standard: str = Field(
        ...,
        description="Accounting standard (e.g. US_GAAP, IFRS).",
    )
    fiscal_year: int = Field(..., ge=0, description="Fiscal year (>= 0).")
    fiscal_period: str = Field(
        ...,
        description="Fiscal period (e.g. FY, Q1, Q2, Q3, Q4).",
    )
    statement_date: date = Field(
        ...,
        description="Reporting period end date for the statement.",
    )
    version_sequence: int = Field(
        ...,
        ge=1,
        description="Statement version sequence number for this fact.",
    )

    metric_code: str = Field(
        ...,
        description="Canonical metric code (e.g. REVENUE, NET_INCOME).",
    )
    metric_label: str | None = Field(
        default=None,
        description="Optional human-readable label for the metric.",
    )
    unit: str = Field(
        ...,
        description="Unit code, typically ISO 4217 currency (e.g. USD).",
    )

    period_start: date | None = Field(
        default=None,
        description="Inclusive start of the fact's reporting period, if known.",
    )
    period_end: date = Field(
        ...,
        description="Inclusive end of the fact's reporting period.",
    )

    value: str = Field(
        ...,
        description="Decimal value represented as a string.",
    )

    dimension_key: str = Field(
        ...,
        description="Stable key representing dimensional context (e.g. segment).",
    )
    dimensions: dict[str, str] = Field(
        ...,
        description="Mapping of dimensional qualifiers, e.g. {'segment': 'US'}.",
    )
    source_line_item: str | None = Field(
        default=None,
        description="Original line-item label from the filing, if available.",
    )


class FactQualityHTTP(BaseModel):
    """HTTP projection of FactQualityDTO."""

    model_config = ConfigDict(extra="forbid")

    cik: str = Field(..., description="Company CIK.")
    statement_type: str = Field(
        ...,
        description="Statement type (e.g. INCOME_STATEMENT).",
    )
    fiscal_year: int = Field(..., ge=0, description="Fiscal year (>= 0).")
    fiscal_period: str = Field(
        ...,
        description="Fiscal period (e.g. FY, Q1, Q2, Q3, Q4).",
    )
    version_sequence: int = Field(
        ...,
        ge=1,
        description="Statement version sequence number.",
    )

    metric_code: str = Field(
        ...,
        description="Canonical metric code for the fact.",
    )
    dimension_key: str = Field(
        ...,
        description="Dimensional key for the fact (e.g. segment).",
    )

    severity: MaterialityClass = Field(
        ...,
        description="Fact-level severity (NONE, LOW, MEDIUM, HIGH).",
    )

    is_present: bool = Field(
        ...,
        description="Whether the fact is present in the data set.",
    )
    is_non_negative: bool | None = Field(
        default=None,
        description="Whether the fact passed the NON_NEGATIVE rule (if applicable).",
    )
    is_consistent_with_history: bool | None = Field(
        default=None,
        description="Whether the fact is consistent with historical behavior (if applicable).",
    )
    has_known_issue: bool = Field(
        ...,
        description="Whether the fact is known to have an issue.",
    )

    details: dict[str, str] | None = Field(
        default=None,
        description="Machine-readable details for the quality evaluation.",
    )


class DQAnomalyHTTP(BaseModel):
    """HTTP projection of DQAnomalyDTO."""

    model_config = ConfigDict(extra="forbid")

    dq_run_id: str = Field(
        ...,
        description="Identifier of the DQ run that produced this anomaly.",
    )
    metric_code: str | None = Field(
        default=None,
        description="Metric code this anomaly refers to, if any.",
    )
    dimension_key: str | None = Field(
        default=None,
        description="Dimension key this anomaly refers to, if any.",
    )
    rule_code: str = Field(
        ...,
        description="Code of the rule that produced this anomaly (e.g. NON_NEGATIVE).",
    )
    severity: MaterialityClass = Field(
        ...,
        description="Anomaly severity (LOW, MEDIUM, HIGH).",
    )
    message: str = Field(
        ...,
        description="Human-readable anomaly description.",
    )
    details: dict[str, str] | None = Field(
        default=None,
        description="Machine-readable details (thresholds, prior values, etc.).",
    )


class StatementDQOverlayHTTP(BaseModel):
    """HTTP projection of StatementDQOverlayDTO."""

    model_config = ConfigDict(extra="forbid")

    cik: str = Field(..., description="Company CIK.")
    statement_type: str = Field(
        ...,
        description="Statement type (e.g. INCOME_STATEMENT).",
    )
    fiscal_year: int = Field(..., ge=0, description="Fiscal year (>= 0).")
    fiscal_period: str = Field(
        ...,
        description="Fiscal period (e.g. FY, Q1, Q2, Q3, Q4).",
    )
    version_sequence: int = Field(
        ...,
        ge=1,
        description="Statement version sequence number.",
    )

    accounting_standard: str = Field(
        ...,
        description="Accounting standard (e.g. US_GAAP, IFRS).",
    )
    statement_date: date = Field(
        ...,
        description="Reporting period end date.",
    )
    currency: str = Field(
        ...,
        description="ISO 4217 currency code (e.g. USD).",
    )

    dq_run_id: str | None = Field(
        default=None,
        description="Identifier of the DQ run used for this overlay, if any.",
    )
    dq_rule_set_version: str | None = Field(
        default=None,
        description="Rule-set version used in the DQ run, if any.",
    )
    dq_executed_at: datetime | None = Field(
        default=None,
        description="Execution timestamp for the DQ run, if any (UTC).",
    )
    max_severity: MaterialityClass | None = Field(
        default=None,
        description="Highest severity observed across facts and anomalies, if any.",
    )

    facts: list[NormalizedFactHTTP] = Field(
        default_factory=list,
        description="Flattened facts for the statement identity.",
    )
    fact_quality: list[FactQualityHTTP] = Field(
        default_factory=list,
        description="Fact-level quality evaluations aligned to the statement.",
    )
    anomalies: list[DQAnomalyHTTP] = Field(
        default_factory=list,
        description="Rule-level anomalies associated with the statement.",
    )


class RunStatementDQResultHTTP(BaseModel):
    """HTTP projection of RunStatementDQResultDTO."""

    model_config = ConfigDict(extra="forbid")

    dq_run_id: str = Field(
        ...,
        description="Identifier of the DQ run that was executed.",
    )
    cik: str = Field(..., description="Company CIK.")
    statement_type: str = Field(
        ...,
        description="Statement type (e.g. INCOME_STATEMENT).",
    )
    fiscal_year: int = Field(..., ge=0, description="Fiscal year (>= 0).")
    fiscal_period: str = Field(
        ...,
        description="Fiscal period (e.g. FY, Q1, Q2, Q3, Q4).",
    )
    version_sequence: int = Field(
        ...,
        ge=1,
        description="Statement version sequence number.",
    )

    rule_set_version: str = Field(
        ...,
        description="Rule-set version used for this DQ run.",
    )
    scope_type: str = Field(
        ...,
        description="Scope of the DQ run (e.g. STATEMENT, STATEMENT_ONLY, WITH_HISTORY).",
    )
    history_lookback: int | None = Field(
        default=None,
        ge=1,
        description="Number of historical periods considered for history-based rules, if any.",
    )

    executed_at: datetime = Field(
        ...,
        description="UTC timestamp when the DQ run executed.",
    )

    facts_evaluated: int = Field(
        ...,
        ge=0,
        description="Total number of facts evaluated by the DQ engine.",
    )
    anomaly_count: int = Field(
        ...,
        ge=0,
        description="Total number of anomalies produced by the DQ engine.",
    )

    max_severity: MaterialityClass | None = Field(
        default=None,
        description="Maximum severity observed in this DQ run, if any.",
    )
