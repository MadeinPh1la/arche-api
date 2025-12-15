# src/arche_api/domain/services/xbrl_mapping_overrides.py
# Copyright (c) Arche.
# SPDX-License-Identifier: MIT
"""XBRL mapping override engine for canonical metrics.

Purpose:
    Provide a deterministic, side-effect-free override engine that can remap or
    suppress canonical metric mappings for EDGAR/XBRL facts based on a
    multi-layer precedence model:

        GLOBAL < INDUSTRY < COMPANY < ANALYST

    The engine operates purely in the domain layer. It does not know about
    SQLAlchemy models, HTTP envelopes, repositories, or logging. Callers are
    responsible for loading MappingOverrideRule instances from persistence
    and for deciding whether/how to persist or log OverrideTrace data.

Layer:
    domain/services

Notes:
    - This module does not perform any I/O.
    - All inputs are immutable value objects; the engine is referentially
      transparent and deterministic.
    - Taxonomy, concept, and dimensional matching rules are intentionally
      conservative to avoid surprising implicit behavior.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from enum import Enum, auto
from typing import Final

from arche_api.domain.enums.canonical_statement_metric import CanonicalStatementMetric
from arche_api.domain.exceptions.edgar import EdgarMappingError

__all__ = [
    "OverrideScope",
    "MappingOverrideRule",
    "OverrideDecision",
    "RuleTraceEntry",
    "OverrideTrace",
    "XBRLMappingOverrideEngine",
    "XBRLMappingOverrideError",
]


class OverrideScope(Enum):
    """Override scope hierarchy for mapping rules.

    The effective precedence is:

        ANALYST > COMPANY > INDUSTRY > GLOBAL

    Scope semantics:

        GLOBAL:
            Applies to all filers unless shadowed by higher scopes.
        INDUSTRY:
            Applies to filers within the same industry classification.
        COMPANY:
            Applies to a specific CIK.
        ANALYST:
            Applies to a specific analyst or configuration profile.
    """

    GLOBAL = auto()
    INDUSTRY = auto()
    COMPANY = auto()
    ANALYST = auto()


@dataclass(frozen=True, slots=True)
class MappingOverrideRule:
    """Immutable override rule for XBRL concept → canonical metric mapping.

    Attributes:
        rule_id:
            Stable identifier for this rule, typically the UUID primary key
            from the ref.edgar_xbrl_mapping_overrides table, represented as a
            string for portability.
        scope:
            OverrideScope indicating where this rule sits in the precedence
            hierarchy.
        source_concept:
            XBRL concept QName this rule applies to (e.g., "us-gaap:Revenues").
        source_taxonomy:
            Optional taxonomy identifier (e.g., "US_GAAP_2024"). When set,
            the rule only applies when the normalization context taxonomy
            matches exactly. When None, the rule is considered taxonomy-agnostic.
        match_cik:
            Optional CIK filter. For COMPANY scope, this should be populated
            with the target company's CIK. For other scopes, it should be None.
        match_industry_code:
            Optional industry classification filter (e.g., GICS or NAICS code)
            for INDUSTRY scope. For other scopes, it should typically be None.
        match_analyst_id:
            Optional analyst or configuration profile identifier for ANALYST
            scope. For other scopes, it should be None.
        match_dimensions:
            Mapping of normalized dimensional qualifiers that must all be
            present on the fact for the rule to match. Matching is performed
            as "subset" semantics; the fact's dimensions must contain at least
            these key/value pairs.
        target_metric:
            CanonicalStatementMetric to apply when this rule wins, or None to
            indicate suppression semantics (i.e., the fact should not map to
            any canonical metric).
        is_suppression:
            When True, this rule forces suppression of the base mapping,
            regardless of target_metric. When False, suppression occurs only
            when target_metric is None.
        priority:
            Integer priority within a given scope. Higher values win when
            multiple rules at the same scope match the same fact. This must
            be deterministic and stable over time.
    """

    rule_id: str
    scope: OverrideScope

    source_concept: str
    source_taxonomy: str | None

    match_cik: str | None
    match_industry_code: str | None
    match_analyst_id: str | None
    match_dimensions: Mapping[str, str]

    target_metric: CanonicalStatementMetric | None
    is_suppression: bool
    priority: int


@dataclass(frozen=True, slots=True)
class OverrideDecision:
    """Final override decision for a single fact/concept.

    Attributes:
        base_metric:
            Canonical metric derived from the base mapping engine, if any,
            before overrides are considered.
        final_metric:
            Canonical metric after applying overrides. May be None when a
            suppression rule wins.
        applied_scope:
            Scope of the winning rule, or None when no rule matched.
        applied_rule_id:
            Identifier of the winning rule, or None when no rule matched.
        was_overridden:
            True if the final_metric differs from the base_metric or if a
            suppression rule was applied. False when overrides had no effect.
    """

    base_metric: CanonicalStatementMetric | None
    final_metric: CanonicalStatementMetric | None
    applied_scope: OverrideScope | None
    applied_rule_id: str | None
    was_overridden: bool


@dataclass(frozen=True, slots=True)
class RuleTraceEntry:
    """Trace entry describing how a single rule was evaluated.

    Attributes:
        rule_id:
            Identifier of the rule under consideration.
        scope:
            Scope of the rule.
        matched:
            True if the rule matched all criteria (taxonomy, entity, and
            dimensions). False otherwise.
        reason:
            Optional short explanation when matched is False. Intended purely
            for diagnostics and logging by callers.
    """

    rule_id: str
    scope: OverrideScope
    matched: bool
    reason: str | None


@dataclass(frozen=True, slots=True)
class OverrideTrace:
    """Structured, serializable trace for a single override evaluation.

    Attributes:
        concept:
            XBRL concept QName for the fact.
        taxonomy:
            Taxonomy identifier from the normalization context.
        fact_dimensions:
            Normalized dimensional qualifiers attached to the fact.
        cik:
            Company CIK.
        industry_code:
            Optional industry classification code for the company.
        analyst_id:
            Optional analyst or configuration profile identifier.
        base_metric:
            Canonical metric from the base mapping engine (may be None).
        decision:
            Final OverrideDecision produced by the engine.
        considered_rules:
            Ordered sequence of RuleTraceEntry instances describing how each
            candidate rule was evaluated.
    """

    concept: str
    taxonomy: str
    fact_dimensions: Mapping[str, str]
    cik: str
    industry_code: str | None
    analyst_id: str | None
    base_metric: CanonicalStatementMetric | None
    decision: OverrideDecision
    considered_rules: tuple[RuleTraceEntry, ...]


class XBRLMappingOverrideError(EdgarMappingError):
    """Raised when override rules are misconfigured or inconsistent."""


class XBRLMappingOverrideEngine:
    """Deterministic, side-effect-free engine for applying mapping overrides.

    The engine evaluates a set of MappingOverrideRule instances for a single
    fact/concept and produces a final OverrideDecision, optionally accompanied
    by an OverrideTrace for diagnostics.

    Precedence model:

        1. Filter rules to those matching the concept and taxonomy.
        2. Partition by scope.
        3. Evaluate scopes in order:

               ANALYST > COMPANY > INDUSTRY > GLOBAL

        4. Within a scope, filter by CIK / industry / analyst and dimensions.
        5. Within the remaining rules at that scope, choose the rule with:

               priority DESC, rule_id ASC

        6. If the winning rule is suppressive, final_metric is None.
           Otherwise, final_metric is rule.target_metric when present,
           or base_metric when target_metric is None and the rule is not
           explicitly suppressive.

    The engine does not perform cross-metric aggregation or numeric
    computations; it only decides which canonical metric (if any) a fact
    should map to.
    """

    _SCOPE_PRECEDENCE: Final[tuple[OverrideScope, ...]] = (
        OverrideScope.ANALYST,
        OverrideScope.COMPANY,
        OverrideScope.INDUSTRY,
        OverrideScope.GLOBAL,
    )

    def apply(
        self,
        *,
        concept: str,
        taxonomy: str,
        fact_dimensions: Mapping[str, str],
        cik: str,
        industry_code: str | None,
        analyst_id: str | None,
        base_metric: CanonicalStatementMetric | None,
        rules: Sequence[MappingOverrideRule],
        debug: bool = False,
    ) -> tuple[OverrideDecision, OverrideTrace | None]:
        """Apply override rules to a single fact/concept in context.

        Args:
            concept:
                XBRL concept QName of the fact (e.g., "us-gaap:Revenues").
            taxonomy:
                Taxonomy identifier from the normalization context
                (e.g., "US_GAAP_2024").
            fact_dimensions:
                Normalized dimensional qualifiers attached to the fact.
            cik:
                Company CIK.
            industry_code:
                Optional industry classification code for the company.
            analyst_id:
                Optional analyst or configuration profile identifier.
            base_metric:
                Canonical metric produced by the base mapping engine, or None
                when the fact is currently unmapped.
            rules:
                Sequence of MappingOverrideRule instances to consider. Callers
                are responsible for pre-loading these from persistence.
            debug:
                When True, the engine produces an OverrideTrace including
                per-rule evaluation details. When False, trace is None.

        Returns:
            Tuple of (OverrideDecision, OverrideTrace | None). The trace is
            only populated when debug is True.

        Raises:
            XBRLMappingOverrideError:
                If rules are structurally inconsistent in a way that prevents
                a deterministic decision.
        """
        matching_candidates, trace_entries = self._filter_candidates(
            concept=concept,
            taxonomy=taxonomy,
            rules=rules,
            debug=debug,
        )

        if not matching_candidates:
            decision = self._decision_without_match(base_metric=base_metric)
            if not debug:
                return decision, None

            trace = self._build_trace(
                concept=concept,
                taxonomy=taxonomy,
                fact_dimensions=fact_dimensions,
                cik=cik,
                industry_code=industry_code,
                analyst_id=analyst_id,
                base_metric=base_metric,
                decision=decision,
                trace_entries=trace_entries,
            )
            return decision, trace

        winning_rule = self._select_winning_rule(
            candidates=matching_candidates,
            fact_dimensions=fact_dimensions,
            cik=cik,
            industry_code=industry_code,
            analyst_id=analyst_id,
            trace_entries=trace_entries,
            debug=debug,
        )

        if winning_rule is None:
            decision = self._decision_without_match(base_metric=base_metric)
        else:
            final_metric = self._compute_final_metric(
                base_metric=base_metric,
                rule=winning_rule,
            )
            was_overridden = final_metric != base_metric
            decision = OverrideDecision(
                base_metric=base_metric,
                final_metric=final_metric,
                applied_scope=winning_rule.scope,
                applied_rule_id=winning_rule.rule_id,
                was_overridden=was_overridden,
            )

        if not debug:
            return decision, None

        trace = self._build_trace(
            concept=concept,
            taxonomy=taxonomy,
            fact_dimensions=fact_dimensions,
            cik=cik,
            industry_code=industry_code,
            analyst_id=analyst_id,
            base_metric=base_metric,
            decision=decision,
            trace_entries=trace_entries,
        )
        return decision, trace

    @staticmethod
    def _decision_without_match(
        *,
        base_metric: CanonicalStatementMetric | None,
    ) -> OverrideDecision:
        """Return the default decision when no rule matches."""
        return OverrideDecision(
            base_metric=base_metric,
            final_metric=base_metric,
            applied_scope=None,
            applied_rule_id=None,
            was_overridden=False,
        )

    @staticmethod
    def _build_trace(
        *,
        concept: str,
        taxonomy: str,
        fact_dimensions: Mapping[str, str],
        cik: str,
        industry_code: str | None,
        analyst_id: str | None,
        base_metric: CanonicalStatementMetric | None,
        decision: OverrideDecision,
        trace_entries: list[RuleTraceEntry],
    ) -> OverrideTrace:
        """Construct an OverrideTrace object from the evaluation context."""
        return OverrideTrace(
            concept=concept,
            taxonomy=taxonomy,
            fact_dimensions=dict(fact_dimensions),
            cik=cik,
            industry_code=industry_code,
            analyst_id=analyst_id,
            base_metric=base_metric,
            decision=decision,
            considered_rules=tuple(trace_entries),
        )

    @staticmethod
    def _filter_candidates(
        *,
        concept: str,
        taxonomy: str,
        rules: Sequence[MappingOverrideRule],
        debug: bool,
    ) -> tuple[list[MappingOverrideRule], list[RuleTraceEntry]]:
        """Filter rules by concept and taxonomy and optionally record trace."""
        matching_candidates: list[MappingOverrideRule] = []
        trace_entries: list[RuleTraceEntry] = []

        for rule in rules:
            if rule.source_concept != concept:
                if debug:
                    trace_entries.append(
                        RuleTraceEntry(
                            rule_id=rule.rule_id,
                            scope=rule.scope,
                            matched=False,
                            reason="concept_mismatch",
                        )
                    )
                continue

            if rule.source_taxonomy is not None and rule.source_taxonomy != taxonomy:
                if debug:
                    trace_entries.append(
                        RuleTraceEntry(
                            rule_id=rule.rule_id,
                            scope=rule.scope,
                            matched=False,
                            reason="taxonomy_mismatch",
                        )
                    )
                continue

            matching_candidates.append(rule)

        return matching_candidates, trace_entries

    def _select_winning_rule(
        self,
        *,
        candidates: Sequence[MappingOverrideRule],
        fact_dimensions: Mapping[str, str],
        cik: str,
        industry_code: str | None,
        analyst_id: str | None,
        trace_entries: list[RuleTraceEntry],
        debug: bool,
    ) -> MappingOverrideRule | None:
        """Select the winning rule given candidates and scope precedence."""
        winning_rule: MappingOverrideRule | None = None

        for scope in self._SCOPE_PRECEDENCE:
            scoped_rules = [r for r in candidates if r.scope is scope]
            if not scoped_rules:
                continue

            scoped_matches: list[MappingOverrideRule] = []
            for rule in scoped_rules:
                matched, reason = self._rule_matches(
                    rule=rule,
                    cik=cik,
                    industry_code=industry_code,
                    analyst_id=analyst_id,
                    fact_dimensions=fact_dimensions,
                )
                if debug:
                    trace_entries.append(
                        RuleTraceEntry(
                            rule_id=rule.rule_id,
                            scope=rule.scope,
                            matched=matched,
                            reason=reason,
                        )
                    )
                if matched:
                    scoped_matches.append(rule)

            if not scoped_matches:
                continue

            scoped_matches.sort(
                key=lambda r: (-r.priority, r.rule_id),
            )
            winning_rule = scoped_matches[0]
            break

        return winning_rule

    @staticmethod
    def _match_scope_entity(
        *,
        rule: MappingOverrideRule,
        cik: str,
        industry_code: str | None,
        analyst_id: str | None,
    ) -> tuple[bool, str | None]:
        """Return whether the rule matches at the entity/scope level."""
        if rule.scope is OverrideScope.COMPANY:
            if not rule.match_cik or rule.match_cik != cik:
                return False, "cik_mismatch"
            return True, None

        if rule.scope is OverrideScope.INDUSTRY:
            if not rule.match_industry_code or rule.match_industry_code != industry_code:
                return False, "industry_mismatch"
            return True, None

        if rule.scope is OverrideScope.ANALYST:
            if not rule.match_analyst_id or rule.match_analyst_id != analyst_id:
                return False, "analyst_mismatch"
            return True, None

        # GLOBAL scope: must not carry any entity qualifiers.
        if any(
            (
                rule.match_cik is not None,
                rule.match_industry_code is not None,
                rule.match_analyst_id is not None,
            )
        ):
            return False, "global_rule_has_entity_qualifiers"

        return True, None

    @staticmethod
    def _dimensions_match(
        *,
        required: Mapping[str, str],
        actual: Mapping[str, str],
    ) -> bool:
        """Return True if all required dimensions are present in the fact."""
        if not required:
            return True

        for key, expected_value in required.items():
            actual_value = actual.get(key)
            if actual_value != expected_value:
                return False
        return True

    @classmethod
    def _rule_matches(
        cls,
        *,
        rule: MappingOverrideRule,
        cik: str,
        industry_code: str | None,
        analyst_id: str | None,
        fact_dimensions: Mapping[str, str],
    ) -> tuple[bool, str | None]:
        """Return whether the given rule matches the supplied context.

        Matching rules:
            - COMPANY scope:
                * rule.match_cik must equal cik.
            - INDUSTRY scope:
                * rule.match_industry_code must equal industry_code (non-None).
            - ANALYST scope:
                * rule.match_analyst_id must equal analyst_id (non-None).
            - GLOBAL scope:
                * match_* fields must be None.

            - Dimensions:
                * rule.match_dimensions must be a subset of fact_dimensions.
        """
        entity_ok, reason = cls._match_scope_entity(
            rule=rule,
            cik=cik,
            industry_code=industry_code,
            analyst_id=analyst_id,
        )
        if not entity_ok:
            return False, reason

        if not cls._dimensions_match(required=rule.match_dimensions, actual=fact_dimensions):
            return False, "dimension_mismatch"

        return True, None

    @staticmethod
    def _compute_final_metric(
        *,
        base_metric: CanonicalStatementMetric | None,
        rule: MappingOverrideRule,
    ) -> CanonicalStatementMetric | None:
        """Compute the final canonical metric given the winning rule.

        Suppression semantics:
            - If rule.is_suppression is True, final_metric is always None.
            - Else, if rule.target_metric is None, final_metric is None.
            - Else, final_metric is rule.target_metric.

        For now, no additional validation is performed between base_metric and
        rule.target_metric; callers are expected to configure rules in a way
        that is semantically consistent with the normalization pipeline.
        """
        if rule.is_suppression:
            return None

        if rule.target_metric is None:
            return None

        return rule.target_metric
