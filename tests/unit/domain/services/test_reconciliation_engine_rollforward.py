from datetime import date
from decimal import Decimal

from stacklion_api.domain.entities.canonical_statement_payload import CanonicalStatementPayload
from stacklion_api.domain.entities.edgar_reconciliation import RollforwardReconciliationRule
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
    fiscal_year: int = 2024,
    fiscal_period: FiscalPeriod = FiscalPeriod.FY,
    core_metrics: dict[CanonicalStatementMetric, Decimal],
) -> CanonicalStatementPayload:
    return CanonicalStatementPayload(
        cik="0000999999",
        statement_type=StatementType.CASH_FLOW_STATEMENT,
        accounting_standard=AccountingStandard.US_GAAP,
        statement_date=date(fiscal_year, 12, 31),
        fiscal_year=fiscal_year,
        fiscal_period=fiscal_period,
        currency="USD",
        unit_multiplier=0,
        core_metrics=core_metrics,
        extra_metrics={},
        dimensions={"consolidation": "CONSOLIDATED"},
        source_accession_id="0000999999-24-000001",
        source_taxonomy="US_GAAP_2024",
        source_version_sequence=1,
    )


def test_rollforward_pass_when_opening_plus_flow_equals_closing() -> None:
    payload = _payload(
        core_metrics={
            CanonicalStatementMetric.CASH_AND_CASH_EQUIVALENTS: Decimal("30"),  # opening
            CanonicalStatementMetric.NET_INCREASE_DECREASE_IN_CASH: Decimal("70"),  # flow
            CanonicalStatementMetric.NET_CASH_FROM_OPERATING_ACTIVITIES: Decimal("0"),  # noise
            # treat NET_INCREASE_DECREASE_IN_CASH as the flow metric
        },
    )

    # For this test: opening + flow = closing == 100
    core = dict(payload.core_metrics)
    core[CanonicalStatementMetric.OTHER_CASH_FLOW_FROM_OPERATIONS] = Decimal("0")
    payload = payload.__class__(  # rebuild with a closing metric
        cik=payload.cik,
        statement_type=payload.statement_type,
        accounting_standard=payload.accounting_standard,
        statement_date=payload.statement_date,
        fiscal_year=payload.fiscal_year,
        fiscal_period=payload.fiscal_period,
        currency=payload.currency,
        unit_multiplier=payload.unit_multiplier,
        core_metrics={
            CanonicalStatementMetric.CASH_AND_CASH_EQUIVALENTS: Decimal("30"),
            CanonicalStatementMetric.NET_INCREASE_DECREASE_IN_CASH: Decimal("70"),
            CanonicalStatementMetric.NET_CASH_FROM_OPERATING_ACTIVITIES: Decimal("0"),
            CanonicalStatementMetric.TOTAL_ASSETS: Decimal("100"),  # abuse as closing for test
        },
        extra_metrics=payload.extra_metrics,
        dimensions=payload.dimensions,
        source_accession_id=payload.source_accession_id,
        source_taxonomy=payload.source_taxonomy,
        source_version_sequence=payload.source_version_sequence,
    )

    rule = RollforwardReconciliationRule(
        rule_id="E11_ROLLFORWARD_CASH",
        name="Opening cash + net change = closing cash",
        category=ReconciliationRuleCategory.ROLLFORWARD,
        severity=MaterialityClass.MEDIUM,
        opening_metric=CanonicalStatementMetric.CASH_AND_CASH_EQUIVALENTS,
        flow_metrics=(CanonicalStatementMetric.NET_INCREASE_DECREASE_IN_CASH,),
        closing_metric=CanonicalStatementMetric.TOTAL_ASSETS,
        period_granularity=FiscalPeriod.FY,
        tolerance=Decimal("0.01"),
    )

    engine = ReconciliationEngine()
    results = engine.run(rules=[rule], statements=[payload])

    assert len(results) == 1
    result = results[0]
    assert result.status == ReconciliationStatus.PASS
    assert result.delta == Decimal("0")


def test_rollforward_warning_when_components_missing() -> None:
    payload = _payload(
        core_metrics={
            CanonicalStatementMetric.CASH_AND_CASH_EQUIVALENTS: Decimal("30"),
            # missing flow and closing
        },
    )

    rule = RollforwardReconciliationRule(
        rule_id="E11_ROLLFORWARD_CASH",
        name="Opening cash + net change = closing cash",
        category=ReconciliationRuleCategory.ROLLFORWARD,
        severity=MaterialityClass.MEDIUM,
        opening_metric=CanonicalStatementMetric.CASH_AND_CASH_EQUIVALENTS,
        flow_metrics=(CanonicalStatementMetric.NET_INCREASE_DECREASE_IN_CASH,),
        closing_metric=CanonicalStatementMetric.TOTAL_ASSETS,
        period_granularity=FiscalPeriod.FY,
        tolerance=Decimal("0.01"),
    )

    engine = ReconciliationEngine()
    results = engine.run(rules=[rule], statements=[payload])

    assert len(results) == 1
    result = results[0]
    assert result.status == ReconciliationStatus.WARNING
    assert result.expected_value is None
    assert result.actual_value is None
    assert result.delta is None
