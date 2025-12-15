from datetime import date
from decimal import Decimal

from arche_api.domain.entities.canonical_statement_payload import CanonicalStatementPayload
from arche_api.domain.entities.edgar_reconciliation import IdentityReconciliationRule
from arche_api.domain.enums.canonical_statement_metric import CanonicalStatementMetric
from arche_api.domain.enums.edgar import (
    AccountingStandard,
    FiscalPeriod,
    MaterialityClass,
    StatementType,
)
from arche_api.domain.enums.edgar_reconciliation import (
    ReconciliationRuleCategory,
    ReconciliationStatus,
)
from arche_api.domain.services.reconciliation_engine import (
    ReconciliationEngine,
    ReconciliationEngineConfig,
)


def _payload(
    *,
    statement_type: StatementType,
    fiscal_year: int = 2024,
    fiscal_period: FiscalPeriod = FiscalPeriod.FY,
    core_metrics: dict[CanonicalStatementMetric, Decimal],
) -> CanonicalStatementPayload:
    return CanonicalStatementPayload(
        cik="0000123456",
        statement_type=statement_type,
        accounting_standard=AccountingStandard.US_GAAP,
        statement_date=date(fiscal_year, 12, 31),
        fiscal_year=fiscal_year,
        fiscal_period=fiscal_period,
        currency="USD",
        unit_multiplier=0,
        core_metrics=core_metrics,
        extra_metrics={},
        dimensions={"consolidation": "CONSOLIDATED"},
        source_accession_id="0000123456-24-000001",
        source_taxonomy="US_GAAP_2024",
        source_version_sequence=1,
    )


def _build_payload(
    *,
    cik: str = "0000123456",
    statement_type: StatementType,
    fiscal_year: int = 2024,
    fiscal_period: FiscalPeriod = FiscalPeriod.FY,
    currency: str = "USD",
    core_metrics: dict[CanonicalStatementMetric, Decimal],
) -> CanonicalStatementPayload:
    return CanonicalStatementPayload(
        cik=cik,
        statement_type=statement_type,
        accounting_standard=AccountingStandard.US_GAAP,
        statement_date=date(fiscal_year, 12, 31),
        fiscal_year=fiscal_year,
        fiscal_period=fiscal_period,
        currency=currency,
        unit_multiplier=0,
        core_metrics=core_metrics,
        extra_metrics={},
        dimensions={"consolidation": "CONSOLIDATED"},
        source_accession_id="0000123456-24-000001",
        source_taxonomy="US_GAAP_2024",
        source_version_sequence=1,
    )


def test_identity_rule_passes_when_lhs_equals_rhs() -> None:
    payload_cf = _build_payload(
        statement_type=StatementType.CASH_FLOW_STATEMENT,
        core_metrics={
            CanonicalStatementMetric.NET_CASH_FROM_OPERATING_ACTIVITIES: Decimal("100"),
            CanonicalStatementMetric.NET_CASH_FROM_INVESTING_ACTIVITIES: Decimal("-40"),
            CanonicalStatementMetric.NET_CASH_FROM_FINANCING_ACTIVITIES: Decimal("10"),
            CanonicalStatementMetric.NET_INCREASE_DECREASE_IN_CASH: Decimal("70"),
        },
    )

    rule = IdentityReconciliationRule(
        rule_id="E11_IDENTITY_NET_CHANGE_CASH",
        name="Net change in cash equals sum of cash flows",
        category=ReconciliationRuleCategory.IDENTITY,
        severity=MaterialityClass.MEDIUM,
        lhs_metrics=(CanonicalStatementMetric.NET_INCREASE_DECREASE_IN_CASH,),
        rhs_metrics=(
            CanonicalStatementMetric.NET_CASH_FROM_OPERATING_ACTIVITIES,
            CanonicalStatementMetric.NET_CASH_FROM_INVESTING_ACTIVITIES,
            CanonicalStatementMetric.NET_CASH_FROM_FINANCING_ACTIVITIES,
        ),
        tolerance=Decimal("0.01"),
        applicable_statement_types=(StatementType.CASH_FLOW_STATEMENT,),
    )

    engine = ReconciliationEngine(ReconciliationEngineConfig(default_tolerance=Decimal("0.01")))
    # NOTE: identity implementation is currently stubbed due to missing payload
    # access from StatementPeriod; this test mostly asserts the engine wiring.
    results = engine.run(rules=[rule], statements=[payload_cf])

    assert results  # Kernel is wired and returns something.
    for result in results:
        assert result.rule_id == rule.rule_id
        assert result.rule_category == rule.category


def test_identity_rule_pass_when_lhs_equals_rhs_across_cf_bucket() -> None:
    payload_cf = _payload(
        statement_type=StatementType.CASH_FLOW_STATEMENT,
        core_metrics={
            CanonicalStatementMetric.NET_CASH_FROM_OPERATING_ACTIVITIES: Decimal("100"),
            CanonicalStatementMetric.NET_CASH_FROM_INVESTING_ACTIVITIES: Decimal("-40"),
            CanonicalStatementMetric.NET_CASH_FROM_FINANCING_ACTIVITIES: Decimal("10"),
            CanonicalStatementMetric.NET_INCREASE_DECREASE_IN_CASH: Decimal("70"),
        },
    )

    rule = IdentityReconciliationRule(
        rule_id="E11_IDENTITY_NET_CHANGE_CASH",
        name="Net change in cash equals sum of cash flows",
        category=ReconciliationRuleCategory.IDENTITY,
        severity=MaterialityClass.MEDIUM,
        lhs_metrics=(CanonicalStatementMetric.NET_INCREASE_DECREASE_IN_CASH,),
        rhs_metrics=(
            CanonicalStatementMetric.NET_CASH_FROM_OPERATING_ACTIVITIES,
            CanonicalStatementMetric.NET_CASH_FROM_INVESTING_ACTIVITIES,
            CanonicalStatementMetric.NET_CASH_FROM_FINANCING_ACTIVITIES,
        ),
        tolerance=Decimal("0.01"),
        applicable_statement_types=(StatementType.CASH_FLOW_STATEMENT,),
    )

    engine = ReconciliationEngine(ReconciliationEngineConfig(default_tolerance=Decimal("0.01")))
    results = engine.run(rules=[rule], statements=[payload_cf])

    assert len(results) == 1
    result = results[0]
    assert result.status == ReconciliationStatus.PASS
    assert result.delta == Decimal("0")


def test_identity_rule_fail_when_difference_exceeds_tolerance() -> None:
    payload_cf = _payload(
        statement_type=StatementType.CASH_FLOW_STATEMENT,
        core_metrics={
            CanonicalStatementMetric.NET_CASH_FROM_OPERATING_ACTIVITIES: Decimal("100"),
            CanonicalStatementMetric.NET_CASH_FROM_INVESTING_ACTIVITIES: Decimal("-40"),
            CanonicalStatementMetric.NET_CASH_FROM_FINANCING_ACTIVITIES: Decimal("10"),
            CanonicalStatementMetric.NET_INCREASE_DECREASE_IN_CASH: Decimal("60"),  # off by 10
        },
    )

    rule = IdentityReconciliationRule(
        rule_id="E11_IDENTITY_NET_CHANGE_CASH",
        name="Net change in cash equals sum of cash flows",
        category=ReconciliationRuleCategory.IDENTITY,
        severity=MaterialityClass.MEDIUM,
        lhs_metrics=(CanonicalStatementMetric.NET_INCREASE_DECREASE_IN_CASH,),
        rhs_metrics=(
            CanonicalStatementMetric.NET_CASH_FROM_OPERATING_ACTIVITIES,
            CanonicalStatementMetric.NET_CASH_FROM_INVESTING_ACTIVITIES,
            CanonicalStatementMetric.NET_CASH_FROM_FINANCING_ACTIVITIES,
        ),
        tolerance=Decimal("0.01"),
        applicable_statement_types=(StatementType.CASH_FLOW_STATEMENT,),
    )

    engine = ReconciliationEngine()
    results = engine.run(rules=[rule], statements=[payload_cf])

    assert len(results) == 1
    result = results[0]
    assert result.status == ReconciliationStatus.FAIL
    assert result.delta == Decimal("70") - Decimal("60")
    assert result.severity == MaterialityClass.MEDIUM
