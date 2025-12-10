from datetime import date
from decimal import Decimal

from stacklion_api.domain.entities.canonical_statement_payload import CanonicalStatementPayload
from stacklion_api.domain.entities.edgar_dq import NormalizedStatementIdentity
from stacklion_api.domain.entities.edgar_normalized_fact import EdgarNormalizedFact
from stacklion_api.domain.entities.edgar_reconciliation import SegmentRollupReconciliationRule
from stacklion_api.domain.enums.canonical_statement_metric import CanonicalStatementMetric
from stacklion_api.domain.enums.edgar import (
    AccountingStandard,
    FiscalPeriod,
    MaterialityClass,
    StatementType,
)
from stacklion_api.domain.enums.edgar_reconciliation import (
    ReconciliationRuleCategory,
    ReconciliationStatus,
)
from stacklion_api.domain.services.reconciliation_engine import ReconciliationEngine


def _payload(
    *,
    cik: str = "0000123456",
    fiscal_year: int = 2024,
    fiscal_period: FiscalPeriod = FiscalPeriod.FY,
) -> CanonicalStatementPayload:
    return CanonicalStatementPayload(
        cik=cik,
        statement_type=StatementType.INCOME_STATEMENT,
        accounting_standard=AccountingStandard.US_GAAP,
        statement_date=date(fiscal_year, 12, 31),
        fiscal_year=fiscal_year,
        fiscal_period=fiscal_period,
        currency="USD",
        unit_multiplier=0,
        core_metrics={},
        extra_metrics={},
        dimensions={"consolidation": "CONSOLIDATED"},
        source_accession_id=f"{cik}-24-000001",
        source_taxonomy="US_GAAP_2024",
        source_version_sequence=1,
    )


def _fact(
    *,
    cik: str,
    fiscal_year: int,
    fiscal_period: FiscalPeriod,
    metric_code: str,
    value: Decimal,
    segment: str | None,
) -> EdgarNormalizedFact:
    dims: dict[str, str] = {}
    if segment is not None:
        dims["segment"] = segment

    return EdgarNormalizedFact(
        cik=cik,
        statement_type=StatementType.INCOME_STATEMENT,
        accounting_standard=AccountingStandard.US_GAAP,
        fiscal_year=fiscal_year,
        fiscal_period=fiscal_period,
        statement_date=date(fiscal_year, 12, 31),
        version_sequence=1,
        metric_code=metric_code,
        metric_label=None,
        unit="USD",
        period_start=None,
        period_end=date(fiscal_year, 12, 31),
        value=value,
        dimensions=dims,
        dimension_key=f"segment={segment}" if segment is not None else "default",
        source_line_item=None,
    )


def _identity_for_payload(payload: CanonicalStatementPayload) -> NormalizedStatementIdentity:
    return NormalizedStatementIdentity(
        cik=payload.cik,
        statement_type=payload.statement_type,
        fiscal_year=payload.fiscal_year,
        fiscal_period=payload.fiscal_period,
        version_sequence=payload.source_version_sequence,
    )


def test_segment_rollup_pass_when_children_sum_to_parent() -> None:
    cik = "0000123456"
    payload = _payload(cik=cik)

    parent_metric = CanonicalStatementMetric.REVENUE
    child_metric = CanonicalStatementMetric.REVENUE

    parent_fact = _fact(
        cik=cik,
        fiscal_year=payload.fiscal_year,
        fiscal_period=payload.fiscal_period,
        metric_code=parent_metric.value,
        value=Decimal("150"),
        segment=None,
    )
    child_facts = [
        _fact(
            cik=cik,
            fiscal_year=payload.fiscal_year,
            fiscal_period=payload.fiscal_period,
            metric_code=child_metric.value,
            value=Decimal("50"),
            segment="US",
        ),
        _fact(
            cik=cik,
            fiscal_year=payload.fiscal_year,
            fiscal_period=payload.fiscal_period,
            metric_code=child_metric.value,
            value=Decimal("100"),
            segment="INTL",
        ),
    ]

    rule = SegmentRollupReconciliationRule(
        rule_id="E11_SEGMENT_REVENUE_ROLLUP",
        name="Segment revenue sums to consolidated revenue",
        category=ReconciliationRuleCategory.SEGMENT,
        severity=MaterialityClass.MEDIUM,
        parent_metric=parent_metric,
        child_metric=child_metric,
        rollup_dimension_key="segment",
        tolerance=Decimal("0.01"),
    )

    engine = ReconciliationEngine()
    identity = _identity_for_payload(payload)

    results = engine.run(
        rules=[rule],
        statements=[payload],
        facts_by_identity={identity: [parent_fact, *child_facts]},
    )

    assert len(results) == 1
    result = results[0]
    assert result.status == ReconciliationStatus.PASS
    assert result.delta == Decimal("0")


def test_segment_rollup_fail_when_children_do_not_sum_to_parent() -> None:
    cik = "0000999999"
    payload = _payload(cik=cik)

    parent_metric = CanonicalStatementMetric.REVENUE
    child_metric = CanonicalStatementMetric.REVENUE

    parent_fact = _fact(
        cik=cik,
        fiscal_year=payload.fiscal_year,
        fiscal_period=payload.fiscal_period,
        metric_code=parent_metric.value,
        value=Decimal("150"),
        segment=None,
    )
    child_fact = _fact(
        cik=cik,
        fiscal_year=payload.fiscal_year,
        fiscal_period=payload.fiscal_period,
        metric_code=child_metric.value,
        value=Decimal("200"),
        segment="US",
    )

    rule = SegmentRollupReconciliationRule(
        rule_id="E11_SEGMENT_REVENUE_ROLLUP",
        name="Segment revenue sums to consolidated revenue",
        category=ReconciliationRuleCategory.SEGMENT,
        severity=MaterialityClass.MEDIUM,
        parent_metric=parent_metric,
        child_metric=child_metric,
        rollup_dimension_key="segment",
        tolerance=Decimal("0.01"),
    )

    engine = ReconciliationEngine()
    identity = _identity_for_payload(payload)

    results = engine.run(
        rules=[rule],
        statements=[payload],
        facts_by_identity={identity: [parent_fact, child_fact]},
    )

    assert len(results) == 1
    result = results[0]
    assert result.status == ReconciliationStatus.FAIL
    assert result.delta == child_fact.value - parent_fact.value
    assert result.severity == MaterialityClass.MEDIUM


def test_segment_rollup_warning_when_parent_or_children_missing() -> None:
    cik = "0000777777"
    payload = _payload(cik=cik)

    parent_metric = CanonicalStatementMetric.REVENUE
    child_metric = CanonicalStatementMetric.REVENUE

    child_fact = _fact(
        cik=cik,
        fiscal_year=payload.fiscal_year,
        fiscal_period=payload.fiscal_period,
        metric_code=child_metric.value,
        value=Decimal("200"),
        segment="US",
    )

    rule = SegmentRollupReconciliationRule(
        rule_id="E11_SEGMENT_REVENUE_ROLLUP",
        name="Segment revenue sums to consolidated revenue",
        category=ReconciliationRuleCategory.SEGMENT,
        severity=MaterialityClass.MEDIUM,
        parent_metric=parent_metric,
        child_metric=child_metric,
        rollup_dimension_key="segment",
        tolerance=Decimal("0.01"),
    )

    engine = ReconciliationEngine()
    identity = _identity_for_payload(payload)

    results = engine.run(
        rules=[rule],
        statements=[payload],
        facts_by_identity={identity: [child_fact]},
    )

    assert len(results) == 1
    result = results[0]
    assert result.status == ReconciliationStatus.WARNING
    assert result.expected_value is None
    assert result.actual_value is None
    assert result.delta is None
