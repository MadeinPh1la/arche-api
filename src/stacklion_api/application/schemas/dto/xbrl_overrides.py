# src/stacklion_api/application/schemas/dto/xbrl_overrides.py
# Copyright (c)
# SPDX-License-Identifier: MIT
"""DTOs for XBRL mapping override observability.

Purpose:
    Application-level data transfer objects for exposing the results of the
    XBRL override observability engine. These DTOs are consumed by
    controllers and presenters to build HTTP responses without leaking
    domain entities or service types across layer boundaries.

Layer:
    application/schemas/dto

Notes:
    - These are transport-agnostic DTOs, not HTTP schemas.
    - HTTP-facing models live under adapters/schemas/http.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass

from stacklion_api.domain.enums.edgar import FiscalPeriod, StatementType


@dataclass(frozen=True)
class OverrideDecisionDTO:
    """Effective override decision for a single canonical metric.

    Attributes:
        base_metric:
            Canonical metric code before override evaluation (e.g., "REVENUE").
        final_metric:
            Canonical metric code after applying overrides, or None when the
            metric has been suppressed.
        applied_rule_id:
            Identifier of the rule that ultimately governed the decision, or
            None when no rule applied.
        applied_scope:
            Scope of the applied rule (e.g., "GLOBAL", "INDUSTRY", "COMPANY",
            "ANALYST"), represented as an integer code aligned with
            OverrideScope, or None when no rule applied.
        is_suppression:
            True when the effective decision suppresses the metric instead of
            remapping it.
    """

    base_metric: str
    final_metric: str | None
    applied_rule_id: str | None
    applied_scope: int | None
    is_suppression: bool


@dataclass(frozen=True)
class OverrideTraceEntryDTO:
    """Single rule-evaluation step in the override trace for a metric.

    Attributes:
        rule_id:
            Stable identifier of the evaluated rule.
        scope:
            Scope the rule operates on (e.g., "GLOBAL", "INDUSTRY", "COMPANY",
            "ANALYST"), represented as an integer code aligned with
            OverrideScope, or None when not applicable.
        matched:
            Whether the rule's match criteria were satisfied for this
            evaluation.
        is_suppression:
            True when the rule, if applied, would suppress the metric.
        base_metric:
            Canonical metric code before applying the rule.
        final_metric:
            Canonical metric code after applying the rule, or None when the
            rule would result in suppression.
        match_dimensions:
            Dimensional constraints considered during evaluation, modeled as a
            mapping from dimension key → member key.
        match_cik:
            Whether the rule matched the company CIK for this evaluation.
        match_industry_code:
            Whether the rule matched the industry classification for this
            evaluation.
        match_analyst_id:
            Whether the rule matched the analyst/profile for this evaluation.
        priority:
            Priority used to resolve conflicts between overlapping rules.
    """

    rule_id: int
    scope: int | None
    matched: bool
    is_suppression: bool
    base_metric: str
    final_metric: str | None
    match_dimensions: Mapping[str, str]
    match_cik: bool
    match_industry_code: bool
    match_analyst_id: bool
    priority: int


@dataclass(frozen=True)
class OverrideRuleApplicationDTO:
    """Summary of how an override rule was applied for a statement identity.

    Attributes:
        rule_id:
            Stable identifier of the override rule.
        scope:
            Scope the rule operates on (e.g., "GLOBAL", "INDUSTRY", "COMPANY",
            "ANALYST"), represented as an integer code aligned with
            OverrideScope.
        priority:
            Priority used to resolve conflicts between overlapping rules.
        action:
            High-level action for the rule (e.g., "REMAP", "SUPPRESS").
        source_concept:
            Source GAAP/IFRS concept QName the rule targets, if any.
        target_metric_code:
            Canonical metric code the rule remaps to, if any.
        target_dimension_key:
            Dimension key the rule targets, if any.
        is_suppression:
            True when the rule suppresses metrics rather than remapping them.
        is_effective:
            True when the rule actually affects at least one metric/fact for
            the evaluated statement identity.
        reason:
            Optional human-readable explanation for why the rule is or is not
            effective.
        contributes_to_metrics:
            True when the rule contributes to at least one canonical metric in
            the evaluated slice.
        times_evaluated:
            Number of times the rule was evaluated across candidate facts.
        times_matched:
            Number of evaluations where the rule's match criteria were
            satisfied.
        times_applied:
            Number of evaluations where the rule actually changed the
            effective metric (remap or suppression).
    """

    rule_id: str
    scope: int
    priority: int
    action: str
    source_concept: str | None
    target_metric_code: str | None
    target_dimension_key: str | None
    is_suppression: bool
    is_effective: bool
    reason: str | None
    contributes_to_metrics: bool
    times_evaluated: int
    times_matched: int
    times_applied: int


@dataclass(frozen=True)
class StatementOverrideTraceDTO:
    """Override observability summary for a single statement identity.

    Attributes:
        cik:
            Company CIK as a normalized string.
        statement_type:
            Statement type for the identity (income statement, balance sheet,
            cash flow statement, etc.).
        fiscal_year:
            Fiscal year associated with the statement.
        fiscal_period:
            Fiscal period associated with the statement (e.g., FY, Q1).
        version_sequence:
            Version sequence number for the statement identity.
        suppression_count:
            Total number of canonical metrics suppressed by overrides for this
            statement identity.
        remap_count:
            Total number of canonical metrics remapped to a different metric
            by overrides for this statement identity.
        decisions:
            Mapping from canonical metric code → OverrideDecisionDTO describing
            the effective override outcome for that metric.
        traces:
            Mapping from canonical metric code → ordered sequence of
            OverrideTraceEntryDTO entries, representing the rule-evaluation
            trace used to arrive at the effective decision.
        dimension_key:
            Optional dimension key filter provided by the caller.
        rules:
            Optional per-rule application summaries. For micro-phases that do
            not yet compute per-rule statistics, this may be an empty
            sequence.
        gaap_concept:
            Optional GAAP/IFRS concept filter used when building the trace.
        canonical_metric_code:
            Optional canonical metric filter used when building the trace.
        total_facts_evaluated:
            Total number of facts evaluated across all metrics for this
            statement identity.
        total_facts_remapped:
            Total number of facts whose canonical metric was changed by
            overrides.
        total_facts_suppressed:
            Total number of facts suppressed by overrides.
    """

    cik: str
    statement_type: StatementType
    fiscal_year: int
    fiscal_period: FiscalPeriod
    version_sequence: int
    suppression_count: int
    remap_count: int
    decisions: Mapping[str, OverrideDecisionDTO]
    traces: Mapping[str, Sequence[OverrideTraceEntryDTO]]
    dimension_key: str | None = None
    rules: Sequence[OverrideRuleApplicationDTO] = ()
    gaap_concept: str | None = None
    canonical_metric_code: str | None = None
    total_facts_evaluated: int = 0
    total_facts_remapped: int = 0
    total_facts_suppressed: int = 0


__all__ = [
    "OverrideDecisionDTO",
    "OverrideTraceEntryDTO",
    "OverrideRuleApplicationDTO",
    "StatementOverrideTraceDTO",
]
