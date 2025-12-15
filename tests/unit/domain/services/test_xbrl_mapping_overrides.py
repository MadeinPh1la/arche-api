# tests/unit/domain/services/test_xbrl_mapping_overrides.py
# Copyright (c)
# SPDX-License-Identifier: MIT
"""Unit tests for the XBRL mapping override engine.

Covers:
    - Scope precedence (ANALYST > COMPANY > INDUSTRY > GLOBAL).
    - Dimensional subset matching.
    - Suppression semantics.
    - Taxonomy filtering.
    - Deterministic decisions given the same rule set.
"""

from __future__ import annotations

from uuid import uuid4

from arche_api.domain.enums.canonical_statement_metric import (
    CanonicalStatementMetric,
)
from arche_api.domain.services.xbrl_mapping_overrides import (
    MappingOverrideRule,
    OverrideScope,
    XBRLMappingOverrideEngine,
)


def _make_rule(
    *,
    scope: OverrideScope,
    source_concept: str = "us-gaap:Revenues",
    source_taxonomy: str | None = "US_GAAP_2024",
    target_metric: CanonicalStatementMetric | None = CanonicalStatementMetric.REVENUE,
    is_suppression: bool = False,
    dimensions: dict[str, str] | None = None,
    cik: str | None = None,
    industry_code: str | None = None,
    analyst_id: str | None = None,
    priority: int = 0,
) -> MappingOverrideRule:
    """Helper to construct a rule with sane defaults."""
    return MappingOverrideRule(
        rule_id=str(uuid4()),
        scope=scope,
        source_concept=source_concept,
        source_taxonomy=source_taxonomy,
        match_cik=cik,
        match_industry_code=industry_code,
        match_analyst_id=analyst_id,
        match_dimensions=dimensions or {},
        target_metric=target_metric,
        is_suppression=is_suppression,
        priority=priority,
    )


def test_no_rules_leaves_base_metric_unchanged() -> None:
    """When no rules are provided, the base metric should pass through."""
    engine = XBRLMappingOverrideEngine()
    base_metric = CanonicalStatementMetric.REVENUE

    decision, trace = engine.apply(
        concept="us-gaap:Revenues",
        taxonomy="US_GAAP_2024",
        fact_dimensions={},
        cik="0000320193",
        industry_code=None,
        analyst_id=None,
        base_metric=base_metric,
        rules=[],
        debug=True,
    )

    assert decision.final_metric == base_metric
    assert decision.applied_scope is None
    assert decision.applied_rule_id is None
    assert decision.was_overridden is False
    assert trace is not None
    assert trace.base_metric == base_metric
    assert trace.decision == decision
    assert trace.considered_rules == ()


def test_scope_precedence_analyst_beats_company_and_global() -> None:
    """ANALYST rules must override COMPANY/INDUSTRY/GLOBAL for the same concept."""
    engine = XBRLMappingOverrideEngine()
    cik = "0000320193"

    global_rule = _make_rule(
        scope=OverrideScope.GLOBAL,
        target_metric=CanonicalStatementMetric.REVENUE,
        priority=0,
    )
    company_rule = _make_rule(
        scope=OverrideScope.COMPANY,
        cik=cik,
        target_metric=CanonicalStatementMetric.NET_INCOME,
        priority=10,
    )
    analyst_rule = _make_rule(
        scope=OverrideScope.ANALYST,
        analyst_id="default_analyst",
        target_metric=CanonicalStatementMetric.OPERATING_INCOME,
        priority=0,
    )

    decision, _ = engine.apply(
        concept="us-gaap:Revenues",
        taxonomy="US_GAAP_2024",
        fact_dimensions={},
        cik=cik,
        industry_code=None,
        analyst_id="default_analyst",
        base_metric=CanonicalStatementMetric.REVENUE,
        rules=[global_rule, company_rule, analyst_rule],
        debug=False,
    )

    assert decision.final_metric == CanonicalStatementMetric.OPERATING_INCOME
    assert decision.applied_scope == OverrideScope.ANALYST
    assert decision.was_overridden is True
    assert decision.applied_rule_id == analyst_rule.rule_id


def test_company_rule_applies_when_no_analyst_rule_matches() -> None:
    """COMPANY rules should win when ANALYST rules do not match the profile."""
    engine = XBRLMappingOverrideEngine()
    cik = "0000320193"

    global_rule = _make_rule(
        scope=OverrideScope.GLOBAL,
        target_metric=CanonicalStatementMetric.REVENUE,
    )
    company_rule = _make_rule(
        scope=OverrideScope.COMPANY,
        cik=cik,
        target_metric=CanonicalStatementMetric.NET_INCOME,
    )
    analyst_rule = _make_rule(
        scope=OverrideScope.ANALYST,
        analyst_id="some_other_analyst",
        target_metric=CanonicalStatementMetric.OPERATING_INCOME,
    )

    decision, _ = engine.apply(
        concept="us-gaap:Revenues",
        taxonomy="US_GAAP_2024",
        fact_dimensions={},
        cik=cik,
        industry_code=None,
        analyst_id="default_analyst",
        base_metric=CanonicalStatementMetric.REVENUE,
        rules=[global_rule, company_rule, analyst_rule],
        debug=False,
    )

    assert decision.final_metric == CanonicalStatementMetric.NET_INCOME
    assert decision.applied_scope == OverrideScope.COMPANY
    assert decision.was_overridden is True
    assert decision.applied_rule_id == company_rule.rule_id


def test_dimension_subset_matching() -> None:
    """Rules should match when their dimensions are a subset of fact dimensions."""
    engine = XBRLMappingOverrideEngine()
    cik = "0000320193"

    dim_rule = _make_rule(
        scope=OverrideScope.GLOBAL,
        dimensions={"segment": "US", "consolidation": "CONSOLIDATED"},
        target_metric=CanonicalStatementMetric.REVENUE,
    )

    # Fact with superset dimensions should match.
    fact_dimensions = {
        "segment": "US",
        "consolidation": "CONSOLIDATED",
        "channel": "ONLINE",
    }

    decision, _ = engine.apply(
        concept="us-gaap:Revenues",
        taxonomy="US_GAAP_2024",
        fact_dimensions=fact_dimensions,
        cik=cik,
        industry_code=None,
        analyst_id=None,
        base_metric=CanonicalStatementMetric.REVENUE,
        rules=[dim_rule],
        debug=False,
    )

    assert decision.final_metric == CanonicalStatementMetric.REVENUE
    assert decision.applied_scope == OverrideScope.GLOBAL
    assert decision.was_overridden is False

    # Fact missing one required dimension should not match.
    bad_dimensions = {"segment": "US"}
    decision2, _ = engine.apply(
        concept="us-gaap:Revenues",
        taxonomy="US_GAAP_2024",
        fact_dimensions=bad_dimensions,
        cik=cik,
        industry_code=None,
        analyst_id=None,
        base_metric=CanonicalStatementMetric.REVENUE,
        rules=[dim_rule],
        debug=False,
    )
    assert decision2.applied_scope is None
    assert decision2.final_metric == CanonicalStatementMetric.REVENUE
    assert decision2.was_overridden is False


def test_suppression_rule_nulls_out_metric() -> None:
    """Suppression rules should force the final metric to None."""
    engine = XBRLMappingOverrideEngine()
    cik = "0000320193"

    suppression_rule = _make_rule(
        scope=OverrideScope.COMPANY,
        cik=cik,
        is_suppression=True,
        target_metric=None,
    )

    decision, _ = engine.apply(
        concept="us-gaap:Revenues",
        taxonomy="US_GAAP_2024",
        fact_dimensions={},
        cik=cik,
        industry_code=None,
        analyst_id=None,
        base_metric=CanonicalStatementMetric.REVENUE,
        rules=[suppression_rule],
        debug=False,
    )

    assert decision.final_metric is None
    assert decision.applied_scope == OverrideScope.COMPANY
    assert decision.was_overridden is True


def test_taxonomy_must_match_when_specified() -> None:
    """Rules with a specific taxonomy should not apply to other taxonomies."""
    engine = XBRLMappingOverrideEngine()
    cik = "0000320193"

    gaap_rule = _make_rule(
        scope=OverrideScope.GLOBAL,
        source_taxonomy="US_GAAP_2024",
        target_metric=CanonicalStatementMetric.REVENUE,
    )
    ifrs_rule = _make_rule(
        scope=OverrideScope.GLOBAL,
        source_taxonomy="IFRS_2024",
        target_metric=CanonicalStatementMetric.NET_INCOME,
    )

    decision, _ = engine.apply(
        concept="us-gaap:Revenues",
        taxonomy="US_GAAP_2024",
        fact_dimensions={},
        cik=cik,
        industry_code=None,
        analyst_id=None,
        base_metric=CanonicalStatementMetric.REVENUE,
        rules=[gaap_rule, ifrs_rule],
        debug=False,
    )

    assert decision.final_metric == CanonicalStatementMetric.REVENUE
    assert decision.applied_rule_id == gaap_rule.rule_id

    # Switch taxonomy: only IFRS rule is eligible.
    decision2, _ = engine.apply(
        concept="us-gaap:Revenues",
        taxonomy="IFRS_2024",
        fact_dimensions={},
        cik=cik,
        industry_code=None,
        analyst_id=None,
        base_metric=CanonicalStatementMetric.REVENUE,
        rules=[gaap_rule, ifrs_rule],
        debug=False,
    )

    assert decision2.final_metric == CanonicalStatementMetric.NET_INCOME
    assert decision2.applied_rule_id == ifrs_rule.rule_id
    assert decision2.was_overridden is True


def test_decisions_are_deterministic_given_same_rules() -> None:
    """Given the same rules and context, the engine should be deterministic."""
    engine = XBRLMappingOverrideEngine()
    cik = "0000320193"

    r1 = _make_rule(
        scope=OverrideScope.GLOBAL,
        target_metric=CanonicalStatementMetric.REVENUE,
        priority=1,
    )
    r2 = _make_rule(
        scope=OverrideScope.GLOBAL,
        target_metric=CanonicalStatementMetric.NET_INCOME,
        priority=0,
    )

    decision1, trace1 = engine.apply(
        concept="us-gaap:Revenues",
        taxonomy="US_GAAP_2024",
        fact_dimensions={"segment": "US"},
        cik=cik,
        industry_code=None,
        analyst_id=None,
        base_metric=CanonicalStatementMetric.REVENUE,
        rules=[r1, r2],
        debug=True,
    )

    decision2, trace2 = engine.apply(
        concept="us-gaap:Revenues",
        taxonomy="US_GAAP_2024",
        fact_dimensions={"segment": "US"},
        cik=cik,
        industry_code=None,
        analyst_id=None,
        base_metric=CanonicalStatementMetric.REVENUE,
        rules=[r1, r2],
        debug=True,
    )

    assert decision1 == decision2
    assert decision1.final_metric == CanonicalStatementMetric.REVENUE
    assert decision1.applied_rule_id == r1.rule_id
    assert trace1 is not None and trace2 is not None
    assert [e.rule_id for e in trace1.considered_rules] == [
        e.rule_id for e in trace2.considered_rules
    ]


def test_industry_rule_beats_global_when_company_and_analyst_do_not_match() -> None:
    """INDUSTRY rules should win over GLOBAL when company/analyst rules do not match."""
    engine = XBRLMappingOverrideEngine()
    cik = "0000999999"

    global_rule = _make_rule(
        scope=OverrideScope.GLOBAL,
        target_metric=CanonicalStatementMetric.OTHER_OPERATING_INCOME_EXPENSE,
        priority=1,
    )
    industry_rule = _make_rule(
        scope=OverrideScope.INDUSTRY,
        industry_code="4510",
        target_metric=CanonicalStatementMetric.NET_INCOME,
        priority=1,
    )

    decision, _ = engine.apply(
        concept="us-gaap:Revenues",
        taxonomy="US_GAAP_2024",
        fact_dimensions={},
        cik=cik,
        industry_code="4510",
        analyst_id=None,
        base_metric=CanonicalStatementMetric.REVENUE,
        rules=[global_rule, industry_rule],
        debug=False,
    )

    assert decision.final_metric == CanonicalStatementMetric.NET_INCOME
    assert decision.applied_scope == OverrideScope.INDUSTRY
    assert decision.was_overridden is True
    assert decision.applied_rule_id == industry_rule.rule_id


def test_tie_breaking_within_scope_uses_priority_then_rule_id() -> None:
    """Within a scope, higher priority wins; ties fall back to rule_id ordering."""
    engine = XBRLMappingOverrideEngine()
    cik = "0000320193"

    # Same scope, different priority.
    low_priority = _make_rule(
        scope=OverrideScope.GLOBAL,
        target_metric=CanonicalStatementMetric.NET_INCOME,
        priority=1,
    )
    high_priority = _make_rule(
        scope=OverrideScope.GLOBAL,
        target_metric=CanonicalStatementMetric.OPERATING_INCOME,
        priority=10,
    )

    decision, _ = engine.apply(
        concept="us-gaap:Revenues",
        taxonomy="US_GAAP_2024",
        fact_dimensions={},
        cik=cik,
        industry_code=None,
        analyst_id=None,
        base_metric=CanonicalStatementMetric.REVENUE,
        rules=[low_priority, high_priority],
        debug=False,
    )

    assert decision.final_metric == CanonicalStatementMetric.OPERATING_INCOME
    assert decision.applied_rule_id == high_priority.rule_id

    # Now force equal priority and check deterministic rule_id ordering.
    # We'll reuse the helper but override priorities to be equal.
    r1 = _make_rule(
        scope=OverrideScope.GLOBAL,
        target_metric=CanonicalStatementMetric.REVENUE,
        priority=5,
    )
    r2 = _make_rule(
        scope=OverrideScope.GLOBAL,
        target_metric=CanonicalStatementMetric.NET_INCOME,
        priority=5,
    )

    decision2, _ = engine.apply(
        concept="us-gaap:Revenues",
        taxonomy="US_GAAP_2024",
        fact_dimensions={},
        cik=cik,
        industry_code=None,
        analyst_id=None,
        base_metric=CanonicalStatementMetric.REVENUE,
        rules=[r1, r2],
        debug=False,
    )

    # With same priority, the implementation sorts by (-priority, rule_id),
    # so the lexicographically smallest rule_id should win.
    winning_id = min(r1.rule_id, r2.rule_id)
    assert decision2.applied_rule_id == winning_id


def test_null_target_metric_without_explicit_suppression_still_drops_metric() -> None:
    """A rule with target_metric=None and is_suppression=False still suppresses the metric."""
    engine = XBRLMappingOverrideEngine()
    cik = "0000320193"

    null_target_rule = _make_rule(
        scope=OverrideScope.GLOBAL,
        target_metric=None,
        is_suppression=False,
        priority=1,
    )

    decision, _ = engine.apply(
        concept="us-gaap:Revenues",
        taxonomy="US_GAAP_2024",
        fact_dimensions={},
        cik=cik,
        industry_code=None,
        analyst_id=None,
        base_metric=CanonicalStatementMetric.REVENUE,
        rules=[null_target_rule],
        debug=False,
    )

    assert decision.base_metric == CanonicalStatementMetric.REVENUE
    assert decision.final_metric is None
    assert decision.applied_scope == OverrideScope.GLOBAL
    assert decision.applied_rule_id == null_target_rule.rule_id
    assert decision.was_overridden is True
