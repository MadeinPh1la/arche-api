# tests/unit/domain/services/test_xbrl_mapping_overrides_engine.py
# SPDX-License-Identifier: MIT
"""Unit tests for the XBRL mapping override engine.

These tests verify:
    * Scope precedence: ANALYST > COMPANY > INDUSTRY > GLOBAL.
    * Priority ordering within a scope.
    * Dimension subset matching semantics.
    * Taxonomy filtering behavior.
    * Suppression vs. remap semantics.
    * Deterministic tie-breaking by rule_id.
"""

from __future__ import annotations

from collections.abc import Mapping

import pytest

from arche_api.domain.enums.canonical_statement_metric import CanonicalStatementMetric
from arche_api.domain.services.xbrl_mapping_overrides import (
    MappingOverrideRule,
    OverrideScope,
    XBRLMappingOverrideEngine,
)


def _make_rule(
    *,
    rule_id: str,
    scope: OverrideScope,
    source_concept: str = "us-gaap:Revenues",
    source_taxonomy: str | None = "US_GAAP_MIN_E10A",
    match_cik: str | None = None,
    match_industry_code: str | None = None,
    match_analyst_id: str | None = None,
    match_dimensions: Mapping[str, str] | None = None,
    target_metric: CanonicalStatementMetric | None = CanonicalStatementMetric.REVENUE,
    is_suppression: bool = False,
    priority: int = 0,
) -> MappingOverrideRule:
    """Helper for building override rules in tests."""
    return MappingOverrideRule(
        rule_id=rule_id,
        scope=scope,
        source_concept=source_concept,
        source_taxonomy=source_taxonomy,
        match_cik=match_cik,
        match_industry_code=match_industry_code,
        match_analyst_id=match_analyst_id,
        match_dimensions=dict(match_dimensions or {}),
        target_metric=target_metric,
        is_suppression=is_suppression,
        priority=priority,
    )


@pytest.fixture()
def engine() -> XBRLMappingOverrideEngine:
    """Return a fresh override engine instance for each test."""
    return XBRLMappingOverrideEngine()


def test_no_rules_returns_base_metric_unchanged(engine: XBRLMappingOverrideEngine) -> None:
    """When no rules are provided, the base metric is preserved."""
    decision, trace = engine.apply(
        concept="us-gaap:Revenues",
        taxonomy="US_GAAP_MIN_E10A",
        fact_dimensions={},
        cik="0000123456",
        industry_code=None,
        analyst_id=None,
        base_metric=CanonicalStatementMetric.REVENUE,
        rules=[],
        debug=True,
    )

    assert decision.base_metric == CanonicalStatementMetric.REVENUE
    assert decision.final_metric == CanonicalStatementMetric.REVENUE
    assert decision.applied_scope is None
    assert decision.applied_rule_id is None
    assert decision.was_overridden is False
    assert trace is not None
    assert trace.decision == decision


def test_global_remap_applies_when_no_higher_scope(engine: XBRLMappingOverrideEngine) -> None:
    """GLOBAL rules remap the metric when no higher-scope rules match."""
    rule = _make_rule(
        rule_id="r-global",
        scope=OverrideScope.GLOBAL,
        target_metric=CanonicalStatementMetric.NET_INCOME,
    )

    decision, _ = engine.apply(
        concept="us-gaap:Revenues",
        taxonomy="US_GAAP_MIN_E10A",
        fact_dimensions={},
        cik="0000123456",
        industry_code=None,
        analyst_id=None,
        base_metric=CanonicalStatementMetric.REVENUE,
        rules=[rule],
        debug=False,
    )

    assert decision.final_metric == CanonicalStatementMetric.NET_INCOME
    assert decision.applied_scope == OverrideScope.GLOBAL
    assert decision.applied_rule_id == "r-global"
    assert decision.was_overridden is True


def test_scope_precedence_company_beats_global(engine: XBRLMappingOverrideEngine) -> None:
    """COMPANY-scope rules override GLOBAL rules for the same concept."""
    global_rule = _make_rule(
        rule_id="r-global",
        scope=OverrideScope.GLOBAL,
        target_metric=CanonicalStatementMetric.REVENUE,
    )
    company_rule = _make_rule(
        rule_id="r-company",
        scope=OverrideScope.COMPANY,
        match_cik="0000123456",
        target_metric=CanonicalStatementMetric.NET_INCOME,
    )

    decision, _ = engine.apply(
        concept="us-gaap:Revenues",
        taxonomy="US_GAAP_MIN_E10A",
        fact_dimensions={},
        cik="0000123456",
        industry_code=None,
        analyst_id=None,
        base_metric=CanonicalStatementMetric.REVENUE,
        rules=[global_rule, company_rule],
        debug=False,
    )

    assert decision.final_metric == CanonicalStatementMetric.NET_INCOME
    assert decision.applied_scope == OverrideScope.COMPANY
    assert decision.applied_rule_id == "r-company"


def test_scope_precedence_analyst_beats_company(engine: XBRLMappingOverrideEngine) -> None:
    """ANALYST-scope rules override COMPANY rules when both match."""
    company_rule = _make_rule(
        rule_id="r-company",
        scope=OverrideScope.COMPANY,
        match_cik="0000123456",
        target_metric=CanonicalStatementMetric.TOTAL_ASSETS,
    )
    analyst_rule = _make_rule(
        rule_id="r-analyst",
        scope=OverrideScope.ANALYST,
        match_analyst_id="profile-1",
        target_metric=CanonicalStatementMetric.NET_INCOME,
    )

    decision, _ = engine.apply(
        concept="us-gaap:Revenues",
        taxonomy="US_GAAP_MIN_E10A",
        fact_dimensions={},
        cik="0000123456",
        industry_code=None,
        analyst_id="profile-1",
        base_metric=CanonicalStatementMetric.REVENUE,
        rules=[company_rule, analyst_rule],
        debug=False,
    )

    assert decision.final_metric == CanonicalStatementMetric.NET_INCOME
    assert decision.applied_scope == OverrideScope.ANALYST
    assert decision.applied_rule_id == "r-analyst"


def test_priority_within_scope_and_tie_breaking(engine: XBRLMappingOverrideEngine) -> None:
    """Within the same scope, highest priority wins; ties break by rule_id ASC."""
    low_priority = _make_rule(
        rule_id="b-low",
        scope=OverrideScope.COMPANY,
        match_cik="0000123456",
        target_metric=CanonicalStatementMetric.TOTAL_ASSETS,
        priority=1,
    )
    high_priority = _make_rule(
        rule_id="a-high",
        scope=OverrideScope.COMPANY,
        match_cik="0000123456",
        target_metric=CanonicalStatementMetric.NET_INCOME,
        priority=10,
    )
    same_priority_a = _make_rule(
        rule_id="a-same",
        scope=OverrideScope.COMPANY,
        match_cik="0000123456",
        target_metric=CanonicalStatementMetric.REVENUE,
        priority=5,
    )
    same_priority_b = _make_rule(
        rule_id="b-same",
        scope=OverrideScope.COMPANY,
        match_cik="0000123456",
        target_metric=CanonicalStatementMetric.CASH_AND_CASH_EQUIVALENTS,
        priority=5,
    )

    decision, _ = engine.apply(
        concept="us-gaap:Revenues",
        taxonomy="US_GAAP_MIN_E10A",
        fact_dimensions={},
        cik="0000123456",
        industry_code=None,
        analyst_id=None,
        base_metric=CanonicalStatementMetric.REVENUE,
        rules=[low_priority, high_priority, same_priority_b, same_priority_a],
        debug=False,
    )

    # Highest priority wins regardless of rule_id.
    assert decision.final_metric == CanonicalStatementMetric.NET_INCOME
    assert decision.applied_rule_id == "a-high"

    # Now drop the high-priority rule to test tie-break by rule_id.
    decision_tie, _ = engine.apply(
        concept="us-gaap:Revenues",
        taxonomy="US_GAAP_MIN_E10A",
        fact_dimensions={},
        cik="0000123456",
        industry_code=None,
        analyst_id=None,
        base_metric=CanonicalStatementMetric.REVENUE,
        rules=[low_priority, same_priority_b, same_priority_a],
        debug=False,
    )

    # same_priority_a and same_priority_b share priority=5; "a-same" wins by rule_id.
    assert decision_tie.final_metric == CanonicalStatementMetric.REVENUE
    assert decision_tie.applied_rule_id == "a-same"


def test_dimension_subset_matching(engine: XBRLMappingOverrideEngine) -> None:
    """Rules require match_dimensions to be a subset of fact dimensions."""
    rule = _make_rule(
        rule_id="r-dim",
        scope=OverrideScope.GLOBAL,
        match_dimensions={"consolidation": "CONSOLIDATED", "operations": "CONTINUING"},
        target_metric=CanonicalStatementMetric.NET_INCOME,
    )

    fact_dimensions = {
        "consolidation": "CONSOLIDATED",
        "operations": "CONTINUING",
        "segment": "TOTAL",
    }

    decision, _ = engine.apply(
        concept="us-gaap:Revenues",
        taxonomy="US_GAAP_MIN_E10A",
        fact_dimensions=fact_dimensions,
        cik="0000123456",
        industry_code=None,
        analyst_id=None,
        base_metric=CanonicalStatementMetric.REVENUE,
        rules=[rule],
        debug=False,
    )

    assert decision.final_metric == CanonicalStatementMetric.NET_INCOME
    assert decision.was_overridden is True


def test_dimension_mismatch_prevents_rule_match(engine: XBRLMappingOverrideEngine) -> None:
    """Dimension mismatch prevents a rule from matching even if scope/entity match."""
    rule = _make_rule(
        rule_id="r-dim-mismatch",
        scope=OverrideScope.COMPANY,
        match_cik="0000123456",
        match_dimensions={"consolidation": "CONSOLIDATED"},
        target_metric=CanonicalStatementMetric.NET_INCOME,
    )

    # consolidation dimension does not match.
    fact_dimensions = {"consolidation": "UNCONSOLIDATED"}

    decision, _ = engine.apply(
        concept="us-gaap:Revenues",
        taxonomy="US_GAAP_MIN_E10A",
        fact_dimensions=fact_dimensions,
        cik="0000123456",
        industry_code=None,
        analyst_id=None,
        base_metric=CanonicalStatementMetric.REVENUE,
        rules=[rule],
        debug=True,
    )

    assert decision.final_metric == CanonicalStatementMetric.REVENUE
    assert decision.applied_rule_id is None
    assert decision.was_overridden is False


def test_taxonomy_mismatch_filtered_before_scope_evaluation(
    engine: XBRLMappingOverrideEngine,
) -> None:
    """Rules with mismatching source_taxonomy are ignored."""
    wrong_taxonomy_rule = _make_rule(
        rule_id="r-wrong-tax",
        scope=OverrideScope.GLOBAL,
        source_taxonomy="US_GAAP_2099",
        target_metric=CanonicalStatementMetric.NET_INCOME,
    )
    agnostic_rule = _make_rule(
        rule_id="r-agnostic",
        scope=OverrideScope.GLOBAL,
        source_taxonomy=None,
        target_metric=CanonicalStatementMetric.TOTAL_ASSETS,
    )

    decision, _ = engine.apply(
        concept="us-gaap:Revenues",
        taxonomy="US_GAAP_MIN_E10A",
        fact_dimensions={},
        cik="0000123456",
        industry_code=None,
        analyst_id=None,
        base_metric=CanonicalStatementMetric.REVENUE,
        rules=[wrong_taxonomy_rule, agnostic_rule],
        debug=False,
    )

    # wrong_taxonomy_rule should be filtered out; taxonomy-agnostic rule remains.
    assert decision.final_metric == CanonicalStatementMetric.TOTAL_ASSETS
    assert decision.applied_rule_id == "r-agnostic"


def test_suppression_rule_forces_final_metric_none(engine: XBRLMappingOverrideEngine) -> None:
    """Suppression rules force final_metric to None even if target_metric is set."""
    suppression_rule = _make_rule(
        rule_id="r-suppress",
        scope=OverrideScope.GLOBAL,
        is_suppression=True,
        target_metric=CanonicalStatementMetric.NET_INCOME,
    )

    decision, _ = engine.apply(
        concept="us-gaap:Revenues",
        taxonomy="US_GAAP_MIN_E10A",
        fact_dimensions={},
        cik="0000123456",
        industry_code=None,
        analyst_id=None,
        base_metric=CanonicalStatementMetric.REVENUE,
        rules=[suppression_rule],
        debug=False,
    )

    assert decision.base_metric == CanonicalStatementMetric.REVENUE
    assert decision.final_metric is None
    assert decision.applied_rule_id == "r-suppress"
    assert decision.was_overridden is True


def test_global_rule_with_entity_qualifiers_never_matches(
    engine: XBRLMappingOverrideEngine,
) -> None:
    """GLOBAL rules carrying entity qualifiers are treated as misconfigured and ignored."""
    misconfigured_global = _make_rule(
        rule_id="r-bad-global",
        scope=OverrideScope.GLOBAL,
        match_cik="0000123456",
        target_metric=CanonicalStatementMetric.NET_INCOME,
    )

    decision, trace = engine.apply(
        concept="us-gaap:Revenues",
        taxonomy="US_GAAP_MIN_E10A",
        fact_dimensions={},
        cik="0000123456",
        industry_code=None,
        analyst_id=None,
        base_metric=CanonicalStatementMetric.REVENUE,
        rules=[misconfigured_global],
        debug=True,
    )

    assert decision.final_metric == CanonicalStatementMetric.REVENUE
    assert decision.applied_rule_id is None
    assert decision.was_overridden is False

    assert trace is not None
    # Ensure the rule is present in the trace and marked as non-matching.
    bad_entries = [e for e in trace.considered_rules if e.rule_id == "r-bad-global"]
    assert bad_entries
    assert bad_entries[0].matched is False
    assert bad_entries[0].reason in {"global_rule_has_entity_qualifiers", "concept_mismatch"}
