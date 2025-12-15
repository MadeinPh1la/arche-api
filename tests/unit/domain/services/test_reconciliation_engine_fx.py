from datetime import date
from decimal import Decimal

from arche_api.domain.entities.canonical_statement_payload import CanonicalStatementPayload
from arche_api.domain.entities.edgar_reconciliation import FxReconciliationRule
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
    cik: str = "0000123456",
    currency: str = "USD",
) -> CanonicalStatementPayload:
    return CanonicalStatementPayload(
        cik=cik,
        statement_type=StatementType.INCOME_STATEMENT,
        accounting_standard=AccountingStandard.US_GAAP,
        statement_date=date(2024, 12, 31),
        fiscal_year=2024,
        fiscal_period=FiscalPeriod.FY,
        currency=currency,
        unit_multiplier=0,
        core_metrics={CanonicalStatementMetric.REVENUE: Decimal("100")},
        extra_metrics={},
        dimensions={"consolidation": "CONSOLIDATED"},
        source_accession_id=f"{cik}-24-000001",
        source_taxonomy="US_GAAP_2024",
        source_version_sequence=1,
    )


def test_fx_rule_stub_always_warns() -> None:
    payload = _payload()

    rule = FxReconciliationRule(
        rule_id="E11_FX_REVENUE_CONSISTENCY",
        name="FX consistency for revenue",
        category=ReconciliationRuleCategory.FX,
        severity=MaterialityClass.MEDIUM,
        base_metric=CanonicalStatementMetric.REVENUE,
        fx_rate_metric=None,
        local_currency="EUR",
        reporting_currency="USD",
        tolerance_bps=100,
        description="Stub FX rule for E11-A; should emit WARNING.",
    )

    engine = ReconciliationEngine()
    results = engine.run(rules=[rule], statements=[payload])

    assert len(results) == 1
    result = results[0]
    assert result.status == ReconciliationStatus.WARNING
    assert result.severity == MaterialityClass.LOW
    assert result.expected_value is None
    assert result.actual_value is None
    assert result.delta is None
    assert result.notes is not None
    assert result.notes["reason"] == "FX_RULE_STUB"
    assert result.notes["base_metric"] == CanonicalStatementMetric.REVENUE.value
