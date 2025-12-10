# src/stacklion_api/adapters/schemas/http/edgar_overrides_schemas.py
# Copyright (c)
# SPDX-License-Identifier: MIT
"""HTTP Schemas: EDGAR XBRL mapping override observability."""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict, Field


class OverrideRuleApplicationHTTP(BaseModel):
    """HTTP projection of OverrideRuleApplicationDTO."""

    model_config = ConfigDict(extra="forbid")

    rule_id: str = Field(
        ...,
        description="Stable identifier for the override rule (e.g. primary key or natural key).",
    )
    scope: str = Field(
        ...,
        description=(
            "Override scope (e.g. GLOBAL, INDUSTRY, COMPANY, ANALYST). "
            "This is a stringified domain enum."
        ),
    )
    priority: int = Field(
        ...,
        ge=0,
        description=(
            "Priority of the rule within its scope. Higher values win when multiple "
            "rules at the same scope match."
        ),
    )

    action: str = Field(
        ...,
        description="Effective action of the rule (e.g. REMAP, SUPPRESS, NO_OP).",
    )

    source_concept: str | None = Field(
        default=None,
        description="Source GAAP/IFRS concept or canonical metric code the rule matches.",
    )
    target_metric_code: str | None = Field(
        default=None,
        description="Target canonical metric code when the rule performs a remap.",
    )
    target_dimension_key: str | None = Field(
        default=None,
        description="Target dimension key when the rule adjusts dimensional context.",
    )

    is_effective: bool = Field(
        ...,
        description="Whether this rule actually changed any facts in the evaluated slice.",
    )
    reason: str | None = Field(
        default=None,
        description="Optional human-readable explanation of why the rule did or did not apply.",
    )

    contributes_to_metrics: bool = Field(
        ...,
        description=(
            "Whether this rule contributes to at least one canonical metric in the "
            "evaluated slice."
        ),
    )


class StatementOverrideTraceHTTP(BaseModel):
    """HTTP projection of StatementOverrideTraceDTO."""

    model_config = ConfigDict(extra="forbid")

    cik: str = Field(
        ...,
        description="Company CIK (zero-padded string).",
    )
    statement_type: str = Field(
        ...,
        description="Statement type (e.g. INCOME_STATEMENT, BALANCE_SHEET, CASH_FLOW_STATEMENT).",
    )
    fiscal_year: int = Field(
        ...,
        ge=0,
        description="Fiscal year for the statement identity (>= 0).",
    )
    fiscal_period: str = Field(
        ...,
        description="Fiscal period code (e.g. FY, Q1, Q2, Q3, Q4).",
    )
    version_sequence: int = Field(
        ...,
        ge=1,
        description="Version sequence for the statement identity (>= 1).",
    )

    gaap_concept: str | None = Field(
        default=None,
        description="Optional GAAP/IFRS concept filter used for this trace.",
    )
    canonical_metric_code: str | None = Field(
        default=None,
        description="Optional canonical metric code filter used for this trace.",
    )
    dimension_key: str | None = Field(
        default=None,
        description="Optional dimension key filter used for this trace.",
    )

    total_facts_evaluated: int = Field(
        ...,
        ge=0,
        description="Number of normalized facts evaluated for this trace.",
    )
    total_facts_remapped: int = Field(
        ...,
        ge=0,
        description="Number of facts whose canonical metric was remapped by overrides.",
    )
    total_facts_suppressed: int = Field(
        ...,
        ge=0,
        description="Number of facts suppressed (dropped) by overrides.",
    )

    rules: list[OverrideRuleApplicationHTTP] = Field(
        default_factory=list,
        description="Per-rule breakdown of how overrides contributed to this slice.",
    )
