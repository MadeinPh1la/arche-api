# src/arche_api/domain/services/reconciliation_engine.py
# Copyright (c)
# SPDX-License-Identifier: MIT
"""EDGAR reconciliation engine (domain kernel).

Purpose:
    Provide a pure domain reconciliation engine that evaluates accounting
    identity, rollforward, FX, calendar, and segment rollup rules over
    canonical normalized statements and/or fact-level views.

Layer:
    domain/services

Notes:
    - Pure domain logic:
        * No logging.
        * No HTTP or transport concerns.
        * No persistence or gateways.
    - This engine operates on canonical statement payloads and normalized
      facts only. Higher layers are responsible for fetching and passing in
      the appropriate data.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from decimal import Decimal

from arche_api.domain.entities.canonical_statement_payload import CanonicalStatementPayload
from arche_api.domain.entities.edgar_dq import NormalizedStatementIdentity
from arche_api.domain.entities.edgar_normalized_fact import EdgarNormalizedFact
from arche_api.domain.entities.edgar_reconciliation import (
    CalendarReconciliationRule,
    FxReconciliationRule,
    IdentityReconciliationRule,
    ReconciliationResult,
    ReconciliationRule,
    RollforwardReconciliationRule,
    SegmentRollupReconciliationRule,
    StatementReconciliationContext,
)
from arche_api.domain.enums.canonical_statement_metric import CanonicalStatementMetric
from arche_api.domain.enums.edgar import FiscalPeriod, MaterialityClass, StatementType
from arche_api.domain.enums.edgar_reconciliation import (
    ReconciliationSeverity,
    ReconciliationStatus,
)
from arche_api.domain.services.reconciliation_calendar import (
    StatementPeriod,
    align_statements_across_types,
    infer_statement_period,
)


@dataclass(frozen=True, slots=True)
class ReconciliationEngineConfig:
    """Configuration for the reconciliation engine.

    Attributes:
        rule_set_version:
            Identifier for the rule set being applied (e.g., "e11_v1").
        default_tolerance:
            Default absolute tolerance for numeric comparisons when a rule
            does not specify its own tolerance.
        fx_tolerance_bps:
            Default relative tolerance for FX rules, expressed in basis
            points (e.g., 100 == 1%).
    """

    rule_set_version: str = "e11_v1"
    default_tolerance: Decimal = Decimal("0.01")
    fx_tolerance_bps: int = 100


class ReconciliationEngine:
    """Pure domain reconciliation engine."""

    def __init__(self, config: ReconciliationEngineConfig | None = None) -> None:
        """Initialize the reconciliation engine.

        Args:
            config:
                Optional configuration. When omitted, defaults are used.
        """
        self._config = config or ReconciliationEngineConfig()

    # ------------------------------------------------------------------ #
    # Public API                                                         #
    # ------------------------------------------------------------------ #

    def run(
        self,
        *,
        rules: Sequence[ReconciliationRule],
        statements: Sequence[CanonicalStatementPayload],
        facts_by_identity: (
            Mapping[NormalizedStatementIdentity, Sequence[EdgarNormalizedFact]] | None
        ) = None,
    ) -> tuple[ReconciliationResult, ...]:
        """Evaluate reconciliation rules over canonical statements.

        Args:
            rules:
                Reconciliation rules to evaluate. Disabled rules are skipped.
            statements:
                Canonical statement payloads across statement types and
                periods. These are grouped by company and fiscal period
                inside the engine.
            facts_by_identity:
                Optional mapping from NormalizedStatementIdentity to the
                corresponding normalized facts. When provided, segment and
                FX rules can use fact-level detail; otherwise, the engine
                relies on payload-level metrics only.

        Returns:
            Deterministically ordered tuple of ReconciliationResult objects.
        """
        if not statements or not rules:
            return ()

        effective_facts = facts_by_identity or {}

        contexts = self._build_statement_contexts(statements, effective_facts)
        periods = [infer_statement_period(ctx.payload) for ctx in contexts]
        alignment = align_statements_across_types(periods)

        results: list[ReconciliationResult] = []

        for rule in rules:
            if not rule.is_enabled:
                continue

            if isinstance(rule, IdentityReconciliationRule):
                results.extend(self._apply_identity_rule(rule=rule, alignment=alignment))
            elif isinstance(rule, RollforwardReconciliationRule):
                results.extend(self._apply_rollforward_rule(rule=rule, periods=periods))
            elif isinstance(rule, FxReconciliationRule):
                results.extend(self._apply_fx_rule(rule=rule, contexts=contexts))
            elif isinstance(rule, CalendarReconciliationRule):
                results.extend(self._apply_calendar_rule(rule=rule, periods=periods))
            elif isinstance(rule, SegmentRollupReconciliationRule):
                results.extend(
                    self._apply_segment_rule(
                        rule=rule,
                        contexts=contexts,
                        facts_by_identity=effective_facts,
                    )
                )
            else:
                # Unknown or unsupported rule type; ignore defensively.
                continue

        results.sort(
            key=lambda r: (
                r.statement_identity.cik,
                r.statement_identity.statement_type.value,
                r.statement_identity.fiscal_year,
                r.statement_identity.fiscal_period.value,
                r.statement_identity.version_sequence,
                r.rule_id,
            )
        )
        return tuple(results)

    # ------------------------------------------------------------------ #
    # Context construction                                               #
    # ------------------------------------------------------------------ #

    def _build_statement_contexts(
        self,
        statements: Sequence[CanonicalStatementPayload],
        facts_by_identity: Mapping[NormalizedStatementIdentity, Sequence[EdgarNormalizedFact]],
    ) -> list[StatementReconciliationContext]:
        """Build reconciliation contexts from canonical payloads."""
        contexts: list[StatementReconciliationContext] = []

        for payload in statements:
            identity = NormalizedStatementIdentity(
                cik=payload.cik,
                statement_type=payload.statement_type,
                fiscal_year=payload.fiscal_year,
                fiscal_period=payload.fiscal_period,
                version_sequence=payload.source_version_sequence,
            )
            facts = facts_by_identity.get(identity)
            contexts.append(
                StatementReconciliationContext(
                    identity=identity,
                    payload=payload,
                    facts=facts,
                )
            )

        return contexts

    # ------------------------------------------------------------------ #
    # Identity rules                                                     #
    # ------------------------------------------------------------------ #

    def _apply_identity_rule(
        self,
        *,
        rule: IdentityReconciliationRule,
        alignment: Mapping[tuple[str, int, FiscalPeriod], Mapping[StatementType, StatementPeriod]],
    ) -> list[ReconciliationResult]:
        """Apply an identity rule across aligned statements."""
        results: list[ReconciliationResult] = []
        tolerance = rule.tolerance if rule.tolerance is not None else self._config.default_tolerance

        for (cik, fiscal_year, fiscal_period), type_map in alignment.items():
            if rule.applicable_statement_types and not any(
                st in type_map for st in rule.applicable_statement_types
            ):
                continue

            bucket_periods = list(type_map.values())
            lhs_value = self._sum_metrics_for_bucket(
                metrics=rule.lhs_metrics, periods=bucket_periods
            )
            rhs_value = self._sum_metrics_for_bucket(
                metrics=rule.rhs_metrics, periods=bucket_periods
            )

            rep = bucket_periods[0]
            identity = NormalizedStatementIdentity(
                cik=cik,
                statement_type=rep.statement_type,
                fiscal_year=fiscal_year,
                fiscal_period=fiscal_period,
                version_sequence=rep.identity.version_sequence,
            )

            if lhs_value is None or rhs_value is None:
                status = ReconciliationStatus.WARNING
                severity: ReconciliationSeverity = MaterialityClass.LOW
                expected = lhs_value
                actual = rhs_value
                delta: Decimal | None = None
            else:
                delta = rhs_value - lhs_value
                if abs(delta) <= tolerance:
                    status = ReconciliationStatus.PASS
                    severity = MaterialityClass.NONE
                else:
                    status = ReconciliationStatus.FAIL
                    severity = rule.severity
                expected = lhs_value
                actual = rhs_value

            notes = {
                "lhs_metrics": [m.value for m in rule.lhs_metrics],
                "rhs_metrics": [m.value for m in rule.rhs_metrics],
                "statement_types": [st.value for st in type_map],
            }

            results.append(
                ReconciliationResult(
                    statement_identity=identity,
                    rule_id=rule.rule_id,
                    rule_category=rule.category,
                    status=status,
                    severity=severity,
                    expected_value=expected,
                    actual_value=actual,
                    delta=delta,
                    dimension_key=None,
                    dimension_labels=None,
                    notes=notes,
                )
            )

        return results

    def _sum_metrics_for_bucket(
        self,
        *,
        metrics: Sequence[CanonicalStatementMetric],
        periods: Sequence[StatementPeriod],
    ) -> Decimal | None:
        """Sum metric values across a bucket of aligned statement periods.

        Args:
            metrics:
                Canonical metrics to aggregate across the bucket.
            periods:
                Aligned statement periods (potentially across statement
                types) for a single (cik, fiscal_year, fiscal_period).

        Returns:
            Sum of all available metric values across all periods, or None
            when none of the metrics are present in any period.
        """
        if not metrics or not periods:
            return None

        metric_set = set(metrics)
        total: Decimal | None = None

        for period in periods:
            core = period.payload.core_metrics
            for metric in metric_set:
                value = core.get(metric)
                if value is None:
                    continue
                total = (total or Decimal("0")) + value

        return total

    # ------------------------------------------------------------------ #
    # Rollforward rules                                                  #
    # ------------------------------------------------------------------ #

    def _apply_rollforward_rule(
        self,
        *,
        rule: RollforwardReconciliationRule,
        periods: Sequence[StatementPeriod],
    ) -> list[ReconciliationResult]:
        """Apply a rollforward rule within individual periods.

        This implementation checks rollforwards where the opening, flow,
        and closing metrics are reported in the same canonical payload
        (e.g., certain cash-flow disclosures). Cross-period rollforwards
        can be implemented in later phases.
        """
        results: list[ReconciliationResult] = []
        tolerance = rule.tolerance if rule.tolerance is not None else self._config.default_tolerance

        for period in periods:
            if rule.period_granularity and period.fiscal_period != rule.period_granularity:
                continue

            core = period.payload.core_metrics
            opening = core.get(rule.opening_metric)
            closing = core.get(rule.closing_metric)

            flow_total: Decimal | None = None
            for metric in rule.flow_metrics:
                value = core.get(metric)
                if value is None:
                    continue
                flow_total = (flow_total or Decimal("0")) + value

            identity = period.identity

            if opening is None or closing is None or flow_total is None:
                status = ReconciliationStatus.WARNING
                severity: ReconciliationSeverity = MaterialityClass.LOW
                expected = None
                actual = None
                delta: Decimal | None = None
                notes = {
                    "reason": "MISSING_ROLLFORWARD_COMPONENTS",
                    "has_opening": opening is not None,
                    "has_closing": closing is not None,
                    "has_flow": flow_total is not None,
                }
            else:
                expected = opening + flow_total
                actual = closing
                delta = actual - expected
                if abs(delta) <= tolerance:
                    status = ReconciliationStatus.PASS
                    severity = MaterialityClass.NONE
                else:
                    status = ReconciliationStatus.FAIL
                    severity = rule.severity
                notes = {
                    "opening_metric": rule.opening_metric.value,
                    "closing_metric": rule.closing_metric.value,
                    "flow_metrics": [m.value for m in rule.flow_metrics],
                }

            results.append(
                ReconciliationResult(
                    statement_identity=identity,
                    rule_id=rule.rule_id,
                    rule_category=rule.category,
                    status=status,
                    severity=severity,
                    expected_value=expected,
                    actual_value=actual,
                    delta=delta,
                    dimension_key=None,
                    dimension_labels=None,
                    notes=notes,
                )
            )

        return results

    # ------------------------------------------------------------------ #
    # FX rules                                                           #
    # ------------------------------------------------------------------ #

    def _apply_fx_rule(
        self,
        *,
        rule: FxReconciliationRule,
        contexts: Sequence[StatementReconciliationContext],
    ) -> list[ReconciliationResult]:
        """Apply FX consistency rules.

        E11-A implements a minimal stub that always emits WARNING results.
        Future phases can introduce richer currency graph checks using
        fact-level detail and external FX metadata when available.
        """
        results: list[ReconciliationResult] = []

        for ctx in contexts:
            identity = ctx.identity
            notes = {
                "reason": "FX_RULE_STUB",
                "base_metric": rule.base_metric.value,
                "fx_rate_metric": rule.fx_rate_metric.value if rule.fx_rate_metric else None,
                "local_currency": rule.local_currency,
                "reporting_currency": rule.reporting_currency,
            }

            results.append(
                ReconciliationResult(
                    statement_identity=identity,
                    rule_id=rule.rule_id,
                    rule_category=rule.category,
                    status=ReconciliationStatus.WARNING,
                    severity=MaterialityClass.LOW,
                    expected_value=None,
                    actual_value=None,
                    delta=None,
                    dimension_key=None,
                    dimension_labels=None,
                    notes=notes,
                )
            )

        return results

    # ------------------------------------------------------------------ #
    # Calendar rules                                                     #
    # ------------------------------------------------------------------ #

    def _apply_calendar_rule(
        self,
        *,
        rule: CalendarReconciliationRule,
        periods: Sequence[StatementPeriod],
    ) -> list[ReconciliationResult]:
        """Apply calendar rules using inferred statement periods."""
        results: list[ReconciliationResult] = []
        if not periods:
            return results

        allowed_fye_months = set(rule.allowed_fye_months)
        sorted_periods = sorted(periods, key=lambda p: p.statement_date)

        for period in sorted_periods:
            identity = period.identity
            fye_month_ok = period.statement_date.month in allowed_fye_months
            status = ReconciliationStatus.PASS if fye_month_ok else ReconciliationStatus.FAIL
            severity: ReconciliationSeverity = (
                rule.severity if not fye_month_ok else MaterialityClass.NONE
            )

            notes = {
                "fye_month": period.statement_date.month,
                "allowed_fye_months": sorted(allowed_fye_months),
            }

            results.append(
                ReconciliationResult(
                    statement_identity=identity,
                    rule_id=rule.rule_id,
                    rule_category=rule.category,
                    status=status,
                    severity=severity,
                    expected_value=None,
                    actual_value=None,
                    delta=None,
                    dimension_key=None,
                    dimension_labels=None,
                    notes=notes,
                )
            )

        return results

    # ------------------------------------------------------------------ #
    # Segment rules                                                      #
    # ------------------------------------------------------------------ #

    def _apply_segment_rule(
        self,
        *,
        rule: SegmentRollupReconciliationRule,
        contexts: Sequence[StatementReconciliationContext],
        facts_by_identity: Mapping[NormalizedStatementIdentity, Sequence[EdgarNormalizedFact]],
    ) -> list[ReconciliationResult]:
        """Apply a segment rollup rule using fact-level detail.

        The rule validates that the consolidated/parent metric equals the
        sum of the corresponding segment/child metrics along the configured
        dimension key (e.g., "segment") for each statement identity that has
        backing facts.
        """
        results: list[ReconciliationResult] = []
        tolerance = rule.tolerance if rule.tolerance is not None else self._config.default_tolerance

        # Build a quick index from identity to payload for metadata (type, period).
        payload_by_identity: dict[NormalizedStatementIdentity, CanonicalStatementPayload] = {
            ctx.identity: ctx.payload for ctx in contexts
        }

        for identity, facts in facts_by_identity.items():
            payload = payload_by_identity.get(identity)
            if payload is None:
                # No payload context for this identity; skip defensively.
                continue

            # Parent fact: same metric code, but WITHOUT the rollup dimension.
            parent_candidates = [
                f
                for f in facts
                if f.metric_code == rule.parent_metric.value
                and rule.rollup_dimension_key not in f.dimensions
            ]

            # Child facts: same metric code, WITH the rollup dimension.
            child_facts = [
                f
                for f in facts
                if f.metric_code == rule.child_metric.value
                and rule.rollup_dimension_key in f.dimensions
            ]

            if not parent_candidates or not child_facts:
                # Not enough data to evaluate; emit a WARNING with no numeric values.
                results.append(
                    ReconciliationResult(
                        statement_identity=identity,
                        rule_id=rule.rule_id,
                        rule_category=rule.category,
                        status=ReconciliationStatus.WARNING,
                        severity=ReconciliationSeverity.LOW,
                        expected_value=None,
                        actual_value=None,
                        delta=None,
                        dimension_key=None,
                        dimension_labels=None,
                        notes={
                            "reason": "SEGMENT_PARENT_OR_CHILD_MISSING",
                            "rollup_dimension_key": rule.rollup_dimension_key,
                            "parent_count": len(parent_candidates),
                            "child_count": len(child_facts),
                        },
                    )
                )
                continue

            # Deterministically choose a parent fact.
            parent_candidates.sort(
                key=lambda f: (
                    f.statement_date,
                    f.version_sequence,
                    f.dimension_key,
                    f.metric_code,
                )
            )
            parent = parent_candidates[-1]

            child_sum: Decimal = sum((f.value for f in child_facts), Decimal("0"))
            delta = child_sum - parent.value

            if abs(delta) <= tolerance:
                status = ReconciliationStatus.PASS
                severity = ReconciliationSeverity.NONE
            else:
                status = ReconciliationStatus.FAIL
                severity = rule.severity

            results.append(
                ReconciliationResult(
                    statement_identity=identity,
                    rule_id=rule.rule_id,
                    rule_category=rule.category,
                    status=status,
                    severity=severity,
                    expected_value=parent.value,
                    actual_value=child_sum,
                    delta=delta,
                    dimension_key=None,
                    dimension_labels=None,
                    notes={
                        "rollup_dimension_key": rule.rollup_dimension_key,
                        "parent_metric": rule.parent_metric.value,
                        "child_metric": rule.child_metric.value,
                        "parent_fact_dimension_key": parent.dimension_key,
                        "child_fact_count": len(child_facts),
                    },
                )
            )

        return results


__all__ = [
    "ReconciliationEngineConfig",
    "ReconciliationEngine",
]
