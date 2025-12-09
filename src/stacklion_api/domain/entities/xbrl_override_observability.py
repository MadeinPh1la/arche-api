# src/stacklion_api/domain/entities/xbrl_override_observability.py
# SPDX-License-Identifier: MIT
"""Domain value objects for XBRL override observability.

Purpose:
    Represent effective override decisions and evaluation traces for
    canonical metrics without introducing logging, HTTP, or ORM concerns.

Layer:
    domain/entities
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass

from stacklion_api.domain.enums.canonical_statement_metric import CanonicalStatementMetric
from stacklion_api.domain.enums.edgar import FiscalPeriod, StatementType
from stacklion_api.domain.services.xbrl_mapping_overrides import OverrideScope

__all__ = [
    "OverrideTraceEntry",
    "EffectiveOverrideDecisionSummary",
    "StatementOverrideObservability",
]


@dataclass(frozen=True, slots=True)
class OverrideTraceEntry:
    """Single rule evaluation step for a canonical metric.

    Attributes:
        rule_id:
            Stable identifier of the override rule.
        scope:
            Scope that the rule operates on (GLOBAL, INDUSTRY, COMPANY, ANALYST),
            or None when not applicable.
        matched:
            Whether the rule's match criteria were satisfied for this evaluation.
        is_suppression:
            True when the rule, if applied, would suppress the metric.
        base_metric:
            Canonical metric targeted before override evaluation.
        final_metric:
            Canonical metric after applying the rule, or None when the rule
            results in suppression.
        match_dimensions:
            Dimensional match constraints evaluated for the rule.
        match_cik:
            CIK constraint for the rule, if any.
        match_industry_code:
            Industry classification constraint for the rule, if any.
        match_analyst_id:
            Analyst/profile constraint for the rule, if any.
        priority:
            Priority value used to resolve conflicts between overlapping rules.
    """

    rule_id: str
    scope: OverrideScope | None
    matched: bool
    is_suppression: bool
    base_metric: CanonicalStatementMetric
    final_metric: CanonicalStatementMetric | None
    match_dimensions: Mapping[str, str]
    match_cik: str | None
    match_industry_code: str | None
    match_analyst_id: str | None
    priority: int

    def __post_init__(self) -> None:
        """Invariant hook for override trace entries.

        Implemented as a no-op to comply with domain entity conventions.
        """
        return


@dataclass(frozen=True, slots=True)
class EffectiveOverrideDecisionSummary:
    """Effective override outcome for a canonical metric.

    Attributes:
        base_metric:
            Canonical metric before override evaluation.
        final_metric:
            Canonical metric after evaluating the override hierarchy, or None
            when the metric is suppressed.
        applied_rule_id:
            Identifier of the winning rule, or None when no rule applied.
        applied_scope:
            Scope of the winning rule, or None when no rule applied.
        is_suppression:
            True when the effective decision suppresses the metric.
    """

    base_metric: CanonicalStatementMetric
    final_metric: CanonicalStatementMetric | None
    applied_rule_id: str | None
    applied_scope: OverrideScope | None
    is_suppression: bool

    def __post_init__(self) -> None:
        """Invariant hook for effective override decisions.

        Implemented as a no-op to comply with domain entity conventions.
        """
        return


@dataclass(frozen=True, slots=True)
class StatementOverrideObservability:
    """Aggregated override observability for a single statement identity.

    Attributes:
        cik:
            Company CIK.
        statement_type:
            Statement type for the identity.
        fiscal_year:
            Fiscal year associated with the statement.
        fiscal_period:
            Fiscal period associated with the statement.
        version_sequence:
            Statement version sequence.
        suppression_count:
            Number of canonical metrics suppressed by overrides.
        remap_count:
            Number of canonical metrics remapped to a different metric by
            overrides.
        per_metric_decisions:
            Mapping from canonical metric to its effective override decision.
        per_metric_traces:
            Mapping from canonical metric to the ordered evaluation trace used
            to arrive at the effective decision.
    """

    cik: str
    statement_type: StatementType
    fiscal_year: int
    fiscal_period: FiscalPeriod
    version_sequence: int
    suppression_count: int
    remap_count: int
    per_metric_decisions: Mapping[CanonicalStatementMetric, EffectiveOverrideDecisionSummary]
    per_metric_traces: Mapping[CanonicalStatementMetric, tuple[OverrideTraceEntry, ...]]

    def __post_init__(self) -> None:
        """Invariant hook for statement-level override observability.

        Implemented as a no-op to comply with domain entity conventions.
        """
        return
