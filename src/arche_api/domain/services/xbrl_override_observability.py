# src/arche_api/domain/services/xbrl_override_observability.py
# SPDX-License-Identifier: MIT
"""Observability service for XBRL mapping overrides.

Purpose:
    Provide a pure-domain service that inspects the effect of XBRL mapping
    override rules for a given normalization context and returns a structured
    summary:

        * Suppression and remap counts per statement.
        * Effective override decision per canonical metric.
        * Optional evaluation trace per metric.

    This service does not perform any logging, metrics emission, or HTTP
    concerns. Adapters are responsible for wiring the result into logs,
    Prometheus, or HTTP DTOs.

Layer:
    domain/services
"""

from __future__ import annotations

from collections import defaultdict
from collections.abc import Iterable, Mapping, Sequence
from datetime import date
from typing import Any, cast

from arche_api.domain.entities.xbrl_override_observability import (
    EffectiveOverrideDecisionSummary,
    OverrideTraceEntry,
    StatementOverrideObservability,
)
from arche_api.domain.enums.canonical_statement_metric import CanonicalStatementMetric
from arche_api.domain.services.edgar_normalization import (
    _CANONICAL_METRIC_REGISTRY,
    EdgarFact,
    NormalizationContext,
)
from arche_api.domain.services.xbrl_mapping_overrides import (
    MappingOverrideRule,
    XBRLMappingOverrideEngine,
)

__all__ = ["XBRLOverrideObservabilityService"]


class XBRLOverrideObservabilityService:
    """Compute override observability for a single normalization context."""

    def __init__(
        self,
        *,
        override_engine: XBRLMappingOverrideEngine | None = None,
    ) -> None:
        """Initialize the service with its collaborators.

        Args:
            override_engine:
                Optional override engine. When omitted, a new
                :class:`XBRLMappingOverrideEngine` instance is created.
        """
        self._override_engine = override_engine or XBRLMappingOverrideEngine()

    def inspect_overrides(
        self,
        context: NormalizationContext,
    ) -> StatementOverrideObservability:
        """Inspect effective overrides for the given normalization context.

        Behavior:
            * If no override rules are present, returns a zeroed-out
              StatementOverrideObservability with empty decision/trace maps.
            * Otherwise, mirrors the canonical metric resolution strategy from
              the normalization engine to determine which facts would feed into
              each canonical metric, and then runs the override engine in
              debug mode to capture decisions and traces.

        Args:
            context:
                NormalizationContext containing facts, override rules, and
                statement identity metadata.

        Returns:
            StatementOverrideObservability summarizing suppression/remap
            counts, effective override decisions, and (optionally) the
            evaluation trace per metric.
        """
        if not context.override_rules:
            # Fast-path: no overrides configured for this context.
            return StatementOverrideObservability(
                cik=context.cik,
                statement_type=context.statement_type,
                fiscal_year=context.fiscal_year,
                fiscal_period=context.fiscal_period,
                version_sequence=context.version_sequence,
                suppression_count=0,
                remap_count=0,
                per_metric_decisions={},
                per_metric_traces={},
            )

        facts_by_concept: dict[str, list[EdgarFact]] = defaultdict(list)
        for fact in context.facts:
            facts_by_concept[fact.concept].append(fact)

        suppression_count = 0
        remap_count = 0
        per_metric_decisions: dict[CanonicalStatementMetric, EffectiveOverrideDecisionSummary] = {}
        per_metric_traces: dict[CanonicalStatementMetric, tuple[OverrideTraceEntry, ...]] = {}

        for registry_metric, concepts in _CANONICAL_METRIC_REGISTRY.items():
            chosen_fact, chosen_concept = _select_fact_for_metric(
                concepts=concepts,
                context=context,
                facts_by_concept=facts_by_concept,
            )
            if chosen_fact is None or chosen_concept is None:
                continue

            (
                decision_summary,
                metric_trace,
                delta_suppression,
                delta_remap,
            ) = self._evaluate_overrides_for_fact(
                registry_metric=registry_metric,
                concept=chosen_concept,
                fact=chosen_fact,
                context=context,
                rules=context.override_rules,
            )

            suppression_count += delta_suppression
            remap_count += delta_remap

            if decision_summary is not None:
                per_metric_decisions[decision_summary.base_metric] = decision_summary
                per_metric_traces[decision_summary.base_metric] = tuple(metric_trace)

        return StatementOverrideObservability(
            cik=context.cik,
            statement_type=context.statement_type,
            fiscal_year=context.fiscal_year,
            fiscal_period=context.fiscal_period,
            version_sequence=context.version_sequence,
            suppression_count=suppression_count,
            remap_count=remap_count,
            per_metric_decisions=per_metric_decisions,
            per_metric_traces=per_metric_traces,
        )

    # ------------------------------------------------------------------ #
    # Internal helpers                                                   #
    # ------------------------------------------------------------------ #

    def _evaluate_overrides_for_fact(
        self,
        *,
        registry_metric: CanonicalStatementMetric,
        concept: str,
        fact: EdgarFact,
        context: NormalizationContext,
        rules: Sequence[MappingOverrideRule],
    ) -> tuple[
        EffectiveOverrideDecisionSummary | None,
        list[OverrideTraceEntry],
        int,
        int,
    ]:
        """Run the override engine for a single (metric, fact) pair."""
        decision, raw_trace = self._override_engine.apply(
            concept=concept,
            taxonomy=context.taxonomy,
            fact_dimensions=fact.dimensions,
            cik=context.cik,
            industry_code=context.industry_code,
            analyst_id=context.analyst_profile_id,
            base_metric=registry_metric,
            rules=rules,
            debug=True,
        )

        is_suppression = decision.final_metric is None
        final_metric = decision.final_metric or registry_metric

        decision_summary = EffectiveOverrideDecisionSummary(
            base_metric=registry_metric,
            final_metric=decision.final_metric,
            applied_rule_id=decision.applied_rule_id,
            applied_scope=decision.applied_scope,
            is_suppression=is_suppression,
        )

        metric_trace: list[OverrideTraceEntry] = []
        if raw_trace is not None:
            # Support both objects exposing `.entries` and plain iterables.
            entries_obj = getattr(raw_trace, "entries", raw_trace)
            entries: Iterable[Any] = cast(Iterable[Any], entries_obj)

            for entry in entries:
                metric_trace.append(
                    OverrideTraceEntry(
                        rule_id=entry.rule_id,
                        scope=entry.scope,
                        matched=entry.matched,
                        is_suppression=entry.is_suppression,
                        base_metric=entry.base_metric,
                        final_metric=entry.final_metric,
                        match_dimensions=entry.match_dimensions,
                        match_cik=entry.match_cik,
                        match_industry_code=entry.match_industry_code,
                        match_analyst_id=entry.match_analyst_id,
                        priority=entry.priority,
                    )
                )

        suppression_delta = 1 if is_suppression else 0
        remap_delta = 1 if not is_suppression and final_metric != registry_metric else 0

        return decision_summary, metric_trace, suppression_delta, remap_delta


def _select_fact_for_metric(
    *,
    concepts: Sequence[str],
    context: NormalizationContext,
    facts_by_concept: Mapping[str, Sequence[EdgarFact]],
) -> tuple[EdgarFact | None, str | None]:
    """Select the fact that would feed into a canonical metric.

    Mirrors the concept resolution strategy from the canonical statement
    normalizer:

        * Iterate registry concepts in order.
        * Prefer facts whose unit matches the statement currency.
        * Break ties deterministically by (period_end/instant_date, fact_id).
    """
    for concept in concepts:
        candidates = list(facts_by_concept.get(concept, ()))
        if not candidates:
            continue

        # Prefer facts matching the reporting currency when possible.
        currency_upper = context.currency.upper().strip()
        preferred = [f for f in candidates if f.unit.upper().strip() == currency_upper]
        if preferred:
            candidates = preferred

        def _sort_key(fact: EdgarFact) -> tuple[date | None, str]:
            ref_date = fact.period_end or fact.instant_date
            return (ref_date, fact.fact_id)

        candidates.sort(key=_sort_key)
        return candidates[-1], concept

    return None, None
