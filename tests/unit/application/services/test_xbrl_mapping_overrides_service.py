from __future__ import annotations

from collections.abc import Mapping, Sequence
from typing import Any

import pytest

from stacklion_api.application.services.xbrl_mapping_overrides import (
    XBRLMappingOverridesService,
)
from stacklion_api.domain.enums.canonical_statement_metric import CanonicalStatementMetric
from stacklion_api.domain.interfaces.repositories.xbrl_mapping_overrides_repository import (
    XBRLMappingOverridesRepository,
)
from stacklion_api.domain.services.xbrl_mapping_overrides import (
    MappingOverrideRule,
    OverrideScope,
)


class _FakeRepo(XBRLMappingOverridesRepository):
    def __init__(self, rules: Sequence[MappingOverrideRule]) -> None:
        self._rules = list(rules)
        self.calls: list[dict[str, Any]] = []

    async def list_rules_for_concept(
        self,
        *,
        concept: str,
        taxonomy: str | None = None,
    ) -> Sequence[MappingOverrideRule]:
        self.calls.append({"concept": concept, "taxonomy": taxonomy})
        return [r for r in self._rules if r.source_concept == concept]


class _FakeDecision:
    def __init__(self, final_metric: CanonicalStatementMetric | None, applied_rule_id: str | None):
        self.final_metric = final_metric
        self.applied_rule_id = applied_rule_id
        self.was_overridden = applied_rule_id is not None
        self.applied_scope = None  # adjust if your real Decision has this


class _FakeEngine:
    def __init__(self) -> None:
        self.calls: list[dict[str, Any]] = []

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
    ) -> tuple[_FakeDecision, Any]:
        self.calls.append(
            {
                "concept": concept,
                "taxonomy": taxonomy,
                "fact_dimensions": dict(fact_dimensions),
                "cik": cik,
                "industry_code": industry_code,
                "analyst_id": analyst_id,
                "base_metric": base_metric,
                "rules": list(rules),
                "debug": debug,
            }
        )
        # Simplest behavior: pick first rule if any, otherwise keep base_metric
        if rules:
            rule = rules[0]
            return _FakeDecision(rule.target_metric, rule.rule_id), {"rules": [rule.rule_id]}
        return _FakeDecision(base_metric, None), {"rules": []}


@pytest.mark.asyncio
async def test_list_rules_for_concept_delegates_to_repo() -> None:
    rules = [
        MappingOverrideRule(
            rule_id="r1",
            scope=OverrideScope.GLOBAL,
            source_concept="us-gaap:Revenues",
            source_taxonomy="US_GAAP_2024",
            match_cik=None,
            match_industry_code=None,
            match_analyst_id=None,
            match_dimensions={},
            target_metric=CanonicalStatementMetric.REVENUE,
            is_suppression=False,
            priority=0,
        ),
        MappingOverrideRule(
            rule_id="r2",
            scope=OverrideScope.GLOBAL,
            source_concept="us-gaap:Assets",
            source_taxonomy="US_GAAP_2024",
            match_cik=None,
            match_industry_code=None,
            match_analyst_id=None,
            match_dimensions={},
            target_metric=CanonicalStatementMetric.TOTAL_ASSETS,
            is_suppression=False,
            priority=0,
        ),
    ]
    repo = _FakeRepo(rules=rules)
    service = XBRLMappingOverridesService(repository=repo, engine=_FakeEngine())

    result = await service.list_rules_for_concept(
        concept="us-gaap:Revenues",
        taxonomy="US_GAAP_2024",
    )

    assert {r.rule_id for r in result} == {"r1"}
    assert repo.calls == [{"concept": "us-gaap:Revenues", "taxonomy": "US_GAAP_2024"}]


@pytest.mark.asyncio
async def test_apply_overrides_calls_engine_with_repo_rules() -> None:
    rule = MappingOverrideRule(
        rule_id="r1",
        scope=OverrideScope.COMPANY,
        source_concept="us-gaap:Revenues",
        source_taxonomy="US_GAAP_2024",
        match_cik="0000123456",
        match_industry_code=None,
        match_analyst_id=None,
        match_dimensions={},
        target_metric=CanonicalStatementMetric.REVENUE,
        is_suppression=False,
        priority=10,
    )
    repo = _FakeRepo(rules=[rule])
    engine = _FakeEngine()
    service = XBRLMappingOverridesService(repository=repo, engine=engine)

    decision, trace = await service.apply_overrides(
        concept="us-gaap:Revenues",
        taxonomy="US_GAAP_2024",
        fact_dimensions={"Segment": "US"},
        cik="0000123456",
        industry_code=None,
        analyst_id=None,
        base_metric=CanonicalStatementMetric.REVENUE,
        debug=True,
    )

    assert decision.final_metric == CanonicalStatementMetric.REVENUE
    assert decision.was_overridden is True  # _FakeDecision implementation
    assert engine.calls[0]["concept"] == "us-gaap:Revenues"
    assert engine.calls[0]["rules"][0].rule_id == "r1"
    assert isinstance(trace, dict)
