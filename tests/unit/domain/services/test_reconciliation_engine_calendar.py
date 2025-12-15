from datetime import date
from decimal import Decimal

from arche_api.domain.entities.canonical_statement_payload import CanonicalStatementPayload
from arche_api.domain.entities.edgar_reconciliation import CalendarReconciliationRule
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
from arche_api.domain.services.reconciliation_engine import ReconciliationEngine


def _payload(
    *,
    statement_date: date,
    fiscal_year: int,
    fiscal_period: FiscalPeriod,
) -> CanonicalStatementPayload:
    return CanonicalStatementPayload(
        cik="0000123456",
        statement_type=StatementType.INCOME_STATEMENT,
        accounting_standard=AccountingStandard.US_GAAP,
        statement_date=statement_date,
        fiscal_year=fiscal_year,
        fiscal_period=fiscal_period,
        currency="USD",
        unit_multiplier=0,
        core_metrics={CanonicalStatementMetric.REVENUE: Decimal("100")},
        extra_metrics={},
        dimensions={"consolidation": "CONSOLIDATED"},
        source_accession_id="0000123456-24-000001",
        source_taxonomy="US_GAAP_2024",
        source_version_sequence=1,
    )


def test_calendar_rule_pass_for_allowed_fye_month() -> None:
    payload_2022 = _payload(
        statement_date=date(2022, 12, 31),
        fiscal_year=2022,
        fiscal_period=FiscalPeriod.FY,
    )
    payload_2023 = _payload(
        statement_date=date(2023, 12, 31),
        fiscal_year=2023,
        fiscal_period=FiscalPeriod.FY,
    )

    rule = CalendarReconciliationRule(
        rule_id="E11_CALENDAR_FYE_MONTH",
        name="Fiscal year-end month is December",
        category=ReconciliationRuleCategory.CALENDAR,
        severity=MaterialityClass.LOW,
        allowed_fye_months=(12,),
        allow_53_week=True,
        max_gap_days=730,
        description=None,
    )

    engine = ReconciliationEngine()
    results = engine.run(rules=[rule], statements=[payload_2022, payload_2023])

    assert len(results) == 2
    for result in results:
        assert result.status == ReconciliationStatus.PASS
        assert result.severity == MaterialityClass.NONE


def test_calendar_rule_fail_for_disallowed_fye_month() -> None:
    payload = _payload(
        statement_date=date(2023, 11, 30),
        fiscal_year=2023,
        fiscal_period=FiscalPeriod.FY,
    )

    rule = CalendarReconciliationRule(
        rule_id="E11_CALENDAR_FYE_MONTH",
        name="Fiscal year-end month is December",
        category=ReconciliationRuleCategory.CALENDAR,
        severity=MaterialityClass.LOW,
        allowed_fye_months=(12,),
        allow_53_week=True,
        max_gap_days=730,
        description=None,
    )

    engine = ReconciliationEngine()
    results = engine.run(rules=[rule], statements=[payload])

    assert len(results) == 1
    result = results[0]
    assert result.status == ReconciliationStatus.FAIL
    assert result.severity == MaterialityClass.LOW
    assert result.notes is not None
    assert result.notes["fye_month"] == 11
