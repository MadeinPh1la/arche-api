from __future__ import annotations

from collections.abc import Sequence
from datetime import date
from typing import Any

from arche_api.domain.entities.xbrl_override_observability import (
    StatementOverrideObservability,
)
from arche_api.domain.enums.canonical_statement_metric import CanonicalStatementMetric
from arche_api.domain.enums.edgar import AccountingStandard, FiscalPeriod, StatementType
from arche_api.domain.services.edgar_normalization import (
    EdgarFact,
    NormalizationContext,
)
from arche_api.domain.services.xbrl_mapping_overrides import (
    MappingOverrideRule,
    OverrideScope,
)
from arche_api.domain.services.xbrl_override_observability import (
    XBRLOverrideObservabilityService,
)


class _FakeDecision:
    def __init__(
        self, *, final_metric: CanonicalStatementMetric | None, applied_rule_id: str | None
    ) -> None:
        self.final_metric = final_metric
        self.applied_rule_id = applied_rule_id
        self.applied_scope = OverrideScope.GLOBAL if applied_rule_id else None


class _FakeTraceEntry:
    def __init__(self, rule_id: str, metric: CanonicalStatementMetric) -> None:
        self.rule_id = rule_id
        self.scope = OverrideScope.GLOBAL
        self.matched = True
        self.is_suppression = False
        self.base_metric = metric
        self.final_metric = metric
        self.match_dimensions: dict[str, str] = {}
        self.match_cik = None
        self.match_industry_code = None
        self.match_analyst_id = None
        self.priority = 0


class _FakeTrace:
    def __init__(self, entries: Sequence[_FakeTraceEntry]) -> None:
        self.entries = tuple(entries)


class _FakeOverrideEngine:
    def __init__(self) -> None:
        self.calls: list[dict[str, Any]] = []

    def apply(self, **kwargs: Any) -> tuple[_FakeDecision, _FakeTrace | None]:
        self.calls.append(kwargs)
        base_metric: CanonicalStatementMetric = kwargs["base_metric"]
        decision = _FakeDecision(final_metric=base_metric, applied_rule_id="rule-1")
        trace = _FakeTrace([_FakeTraceEntry("rule-1", base_metric)])
        return decision, trace


def _empty_context() -> NormalizationContext:
    return NormalizationContext(
        cik="0000123456",
        statement_type=StatementType.INCOME_STATEMENT,
        accounting_standard=AccountingStandard.US_GAAP,
        statement_date=date(2024, 12, 31),
        fiscal_year=2024,
        fiscal_period=FiscalPeriod.FY,
        currency="USD",
        accession_id="0000000000-24-000001",
        taxonomy="US_GAAP_MIN_E10A",
        version_sequence=1,
        facts=(),
        override_rules=(),
        enable_override_trace=False,
    )


def test_inspect_overrides_no_rules_returns_zero_counts() -> None:
    context = _empty_context()
    svc = XBRLOverrideObservabilityService()

    result = svc.inspect_overrides(context)

    assert isinstance(result, StatementOverrideObservability)
    assert result.cik == context.cik
    assert result.suppression_count == 0
    assert result.remap_count == 0
    assert result.per_metric_decisions == {}
    assert result.per_metric_traces == {}


def test_inspect_overrides_with_fake_engine_populates_decisions() -> None:
    # Single fact + single override rule; fake engine always returns a decision.
    fact = EdgarFact(
        fact_id="f1",
        concept="us-gaap:Revenues",
        value="100",
        unit="USD",
        decimals=0,
        period_start=None,
        period_end=date(2024, 12, 31),
        instant_date=None,
        dimensions={},
    )

    context = NormalizationContext(
        cik="0000123456",
        statement_type=StatementType.INCOME_STATEMENT,
        accounting_standard=AccountingStandard.US_GAAP,
        statement_date=date(2024, 12, 31),
        fiscal_year=2024,
        fiscal_period=FiscalPeriod.FY,
        currency="USD",
        accession_id="0000000000-24-000001",
        taxonomy="US_GAAP_MIN_E10A",
        version_sequence=1,
        facts=(fact,),
        override_rules=(
            MappingOverrideRule(
                rule_id="rule-1",
                scope=OverrideScope.GLOBAL,
                source_concept="us-gaap:Revenues",
                source_taxonomy=None,
                match_cik=None,
                match_industry_code=None,
                match_analyst_id=None,
                match_dimensions={},
                target_metric=CanonicalStatementMetric.REVENUE,
                is_suppression=False,
                priority=0,
            ),
        ),
        enable_override_trace=True,
    )

    fake_engine = _FakeOverrideEngine()
    svc = XBRLOverrideObservabilityService(override_engine=fake_engine)

    result = svc.inspect_overrides(context)

    assert result.suppression_count == 0
    # At least one remap/decision recorded.
    assert result.per_metric_decisions
    # Trace present for the decided metric.
    metric = next(iter(result.per_metric_decisions.keys()))
    assert result.per_metric_traces[metric]
    # Fake engine should have been called at least once.
    assert fake_engine.calls
