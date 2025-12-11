# src/stacklion_api/domain/entities/edgar_reconciliation.py
# Copyright (c)
# SPDX-License-Identifier: MIT
"""EDGAR reconciliation domain entities.

Purpose:
    Define reconciliation rule specifications, evaluation contexts, and
    reconciliation results for the EDGAR reconciliation engine.

Layer:
    domain/entities

Notes:
    - Pure domain types:
        * No logging.
        * No HTTP or transport concerns.
        * No persistence or gateways.
    - Rules are modeled as simple dataclasses; the engine operates over
      a tagged union of rule types.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import date
from decimal import Decimal
from typing import Any

from stacklion_api.domain.entities.canonical_statement_payload import CanonicalStatementPayload
from stacklion_api.domain.entities.edgar_dq import NormalizedStatementIdentity
from stacklion_api.domain.entities.edgar_normalized_fact import EdgarNormalizedFact
from stacklion_api.domain.enums.canonical_statement_metric import CanonicalStatementMetric
from stacklion_api.domain.enums.edgar import FiscalPeriod, StatementType
from stacklion_api.domain.enums.edgar_reconciliation import (
    ReconciliationRuleCategory,
    ReconciliationSeverity,
    ReconciliationStatus,
)

# --------------------------------------------------------------------------- #
# Shared types                                                                #
# --------------------------------------------------------------------------- #

# Simple alias; kept distinct in type hints without NewType complexity.
ReconciliationRuleId = str


@dataclass(frozen=True, slots=True)
class StatementReconciliationContext:
    """Context for reconciling a single statement.

    Attributes:
        identity:
            Normalized statement identity for the payload.
        payload:
            Canonical normalized statement payload.
        facts:
            Optional normalized facts backing the payload. When None,
            the engine operates purely at the payload level.
    """

    identity: NormalizedStatementIdentity
    payload: CanonicalStatementPayload
    facts: Sequence[EdgarNormalizedFact] | None = None

    def __post_init__(self) -> None:
        """Hook for enforcing invariants on reconciliation contexts.

        Currently a no-op implementation that satisfies domain entity
        conventions. Invariants can be tightened later without changing
        the public API.
        """
        return


@dataclass(frozen=True, slots=True)
class ReconciliationResult:
    """Single reconciliation rule evaluation result.

    Attributes:
        statement_identity:
            Identity of the statement for which the rule was evaluated.
        rule_id:
            Stable identifier for the rule.
        rule_category:
            Category of the rule (IDENTITY, ROLLFORWARD, etc.).
        status:
            Evaluation outcome (PASS, FAIL, WARNING).
        severity:
            Severity classification aligned with MaterialityClass.
        expected_value:
            Expected numeric value under the rule, when applicable.
        actual_value:
            Actual numeric value observed in the data, when applicable.
        delta:
            Difference actual - expected, when applicable.
        dimension_key:
            Optional dimension key when the rule is dimension-specific.
        dimension_labels:
            Optional human-readable labels for the dimensional slice.
        notes:
            Optional machine-readable diagnostic payload.
    """

    statement_identity: NormalizedStatementIdentity
    rule_id: ReconciliationRuleId
    rule_category: ReconciliationRuleCategory
    status: ReconciliationStatus
    severity: ReconciliationSeverity
    expected_value: Decimal | None
    actual_value: Decimal | None
    delta: Decimal | None
    dimension_key: str | None
    dimension_labels: Mapping[str, str] | None
    notes: Mapping[str, Any] | None

    def __post_init__(self) -> None:
        """Hook for enforcing invariants on reconciliation results.

        Currently implemented as a no-op. This exists to satisfy domain
        conventions and can be extended later with stronger validation.
        """
        return


# --------------------------------------------------------------------------- #
# Rule specifications                                                         #
# --------------------------------------------------------------------------- #


@dataclass(frozen=True, slots=True)
class IdentityReconciliationRule:
    """Accounting identity rule across statements.

    Attributes:
        rule_id:
            Stable identifier for the rule.
        name:
            Short human-readable name.
        category:
            Rule category (must be IDENTITY).
        severity:
            Severity classification for FAIL outcomes.
        lhs_metrics:
            Metrics on the left-hand side of the identity.
        rhs_metrics:
            Metrics on the right-hand side of the identity.
        tolerance:
            Optional absolute tolerance for the identity. When None, the
            engine falls back to its default tolerance.
        applicable_statement_types:
            Optional statement types this rule should apply to. When None
            or empty, the rule applies wherever the required metrics are
            present in the aligned bucket.
        description:
            Optional longer description.
        is_enabled:
            Whether the rule is active.
    """

    rule_id: ReconciliationRuleId
    name: str
    category: ReconciliationRuleCategory
    severity: ReconciliationSeverity
    lhs_metrics: tuple[CanonicalStatementMetric, ...]
    rhs_metrics: tuple[CanonicalStatementMetric, ...]
    tolerance: Decimal | None = None
    applicable_statement_types: tuple[StatementType, ...] | None = None
    description: str | None = None
    is_enabled: bool = True

    def __post_init__(self) -> None:
        """Hook for enforcing invariants on identity rules.

        Currently implemented as a no-op. Category validation is handled
        by the reconciliation engine, not the entity constructor.
        """
        return


@dataclass(frozen=True, slots=True)
class RollforwardReconciliationRule:
    """Rollforward rule within or across periods.

    Attributes:
        rule_id:
            Stable identifier for the rule.
        name:
            Short human-readable name.
        category:
            Rule category (must be ROLLFORWARD).
        severity:
            Severity classification for FAIL outcomes.
        opening_metric:
            Metric expected to represent the opening balance.
        flow_metrics:
            Metrics representing flows during the period.
        closing_metric:
            Metric expected to represent the closing balance.
        period_granularity:
            Optional fiscal period granularity this rule applies to
            (e.g., FiscalPeriod.FY). When None, applies to all periods.
        tolerance:
            Optional absolute tolerance. When None, the engine's default
            tolerance is used.
        description:
            Optional longer description.
        is_enabled:
            Whether the rule is active.
    """

    rule_id: ReconciliationRuleId
    name: str
    category: ReconciliationRuleCategory
    severity: ReconciliationSeverity
    opening_metric: CanonicalStatementMetric
    flow_metrics: tuple[CanonicalStatementMetric, ...]
    closing_metric: CanonicalStatementMetric
    period_granularity: FiscalPeriod | None = None
    tolerance: Decimal | None = None
    description: str | None = None
    is_enabled: bool = True

    def __post_init__(self) -> None:
        """Hook for enforcing invariants on rollforward rules.

        Currently implemented as a no-op to satisfy domain entity
        conventions without constraining early rule design.
        """
        return


@dataclass(frozen=True, slots=True)
class FxReconciliationRule:
    """Multi-currency consistency rule.

    Attributes:
        rule_id:
            Stable identifier for the rule.
        name:
            Short human-readable name.
        category:
            Rule category (must be FX).
        severity:
            Severity classification for FAIL outcomes.
        base_metric:
            Metric in the reporting currency to check.
        fx_rate_metric:
            Optional metric that provides the FX rate used to translate
            from local to reporting currency.
        local_currency:
            Expected local currency code, when applicable.
        reporting_currency:
            Expected reporting currency code.
        tolerance_bps:
            Optional tolerance in basis points for FX consistency checks.
            When None, the engine uses its default FX tolerance.
        description:
            Optional longer description.
        is_enabled:
            Whether the rule is active.
    """

    rule_id: ReconciliationRuleId
    name: str
    category: ReconciliationRuleCategory
    severity: ReconciliationSeverity
    base_metric: CanonicalStatementMetric
    fx_rate_metric: CanonicalStatementMetric | None
    local_currency: str
    reporting_currency: str
    tolerance_bps: int | None = None
    description: str | None = None
    is_enabled: bool = True

    def __post_init__(self) -> None:
        """Hook for enforcing invariants on FX rules.

        Currently implemented as a no-op. FX semantics are enforced by
        the reconciliation engine.
        """
        return


@dataclass(frozen=True, slots=True)
class CalendarReconciliationRule:
    """Calendar / fiscal-year behavior rule.

    Attributes:
        rule_id:
            Stable identifier for the rule.
        name:
            Short human-readable name.
        category:
            Rule category (must be CALENDAR).
        severity:
            Severity classification for FAIL outcomes.
        allowed_fye_months:
            Allowed fiscal year-end months (1–12).
        allow_53_week:
            Whether 53-week years are allowed.
        max_gap_days:
            Maximum allowed gap between fiscal year-end dates before the
            calendar is considered irregular.
        description:
            Optional longer description.
        is_enabled:
            Whether the rule is active.
    """

    rule_id: ReconciliationRuleId
    name: str
    category: ReconciliationRuleCategory
    severity: ReconciliationSeverity
    allowed_fye_months: tuple[int, ...]
    allow_53_week: bool = True
    max_gap_days: int = 730
    description: str | None = None
    is_enabled: bool = True

    def __post_init__(self) -> None:
        """Hook for enforcing invariants on calendar rules.

        Currently implemented as a no-op with minimal structural
        validation handled in the engine.
        """
        return


@dataclass(frozen=True, slots=True)
class SegmentRollupReconciliationRule:
    """Segment / dimensional rollup rule.

    Attributes:
        rule_id:
            Stable identifier for the rule.
        name:
            Short human-readable name.
        category:
            Rule category (must be SEGMENT).
        severity:
            Severity classification for FAIL outcomes.
        parent_metric:
            Metric representing the consolidated / parent total.
        child_metric:
            Metric representing the segment / child values.
        rollup_dimension_key:
            Dimension key along which the rollup is evaluated (e.g., "segment").
        tolerance:
            Optional absolute tolerance for the rollup.
        description:
            Optional longer description.
        is_enabled:
            Whether the rule is active.
    """

    rule_id: ReconciliationRuleId
    name: str
    category: ReconciliationRuleCategory
    severity: ReconciliationSeverity
    parent_metric: CanonicalStatementMetric
    child_metric: CanonicalStatementMetric
    rollup_dimension_key: str
    tolerance: Decimal | None = None
    description: str | None = None
    is_enabled: bool = True

    def __post_init__(self) -> None:
        """Hook for enforcing invariants on segment rollup rules.

        Currently implemented as a no-op. Dimensional semantics are
        handled by the reconciliation engine.
        """
        return


# Tagged union for rule inputs to the engine.
ReconciliationRule = (
    IdentityReconciliationRule
    | RollforwardReconciliationRule
    | FxReconciliationRule
    | CalendarReconciliationRule
    | SegmentRollupReconciliationRule
)


@dataclass(slots=True)
class StatementAlignmentResult:
    """Domain entity representing a single statement alignment result.

    This entity is produced by the reconciliation/stitching engine and is
    structurally compatible with the StatementAlignmentRecord protocol used
    by the alignment repository.

    Attributes:
        cik: Issuer CIK for the statement.
        statement_type: Type of statement (e.g., INCOME_STATEMENT, BALANCE_SHEET).
        fiscal_year: Fiscal year of the statement.
        fiscal_period: Fiscal period code (e.g., "FY", "Q1").
        statement_date: Statement date (period end).
        version_sequence: Monotonic version sequence for restatements.
        fye_date: Company fiscal year-end date, if known.
        is_53_week_year: Whether the fiscal year is a 53-week year.
        period_start: Period start date, if inferred.
        period_end: Period end date, if inferred/overridden.
        alignment_status: Status string (e.g., "ALIGNED", "PARTIAL", "MISSING").
        is_partial_period: Whether this period is partial vs. full.
        is_off_cycle_period: Whether this period is off the regular filing cycle.
        is_irregular_calendar: Whether an irregular calendar was detected.
        details: Optional structured metadata for diagnostics.
    """

    cik: str
    statement_type: StatementType
    fiscal_year: int
    fiscal_period: str
    statement_date: date
    version_sequence: int

    fye_date: date | None = None
    is_53_week_year: bool = False
    period_start: date | None = None
    period_end: date | None = None
    alignment_status: str = "ALIGNED"
    is_partial_period: bool = False
    is_off_cycle_period: bool = False
    is_irregular_calendar: bool = False
    details: dict[str, Any] | None = None

    def __post_init__(self) -> None:
        """Enforce basic invariants for alignment results.

        Raises:
            ValueError: If core identity fields are missing or invalid.
        """
        if not self.cik:
            raise ValueError("cik must be non-empty for StatementAlignmentResult.")
        if self.version_sequence < 1:
            raise ValueError("version_sequence must be >= 1 for StatementAlignmentResult.")


__all__ = [
    "ReconciliationRuleId",
    "StatementReconciliationContext",
    "ReconciliationResult",
    "IdentityReconciliationRule",
    "RollforwardReconciliationRule",
    "FxReconciliationRule",
    "CalendarReconciliationRule",
    "SegmentRollupReconciliationRule",
    "ReconciliationRule",
    "StatementAlignmentResult",
]
