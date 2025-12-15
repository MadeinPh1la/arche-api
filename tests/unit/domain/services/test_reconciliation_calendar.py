from datetime import date
from decimal import Decimal

from arche_api.domain.entities.canonical_statement_payload import CanonicalStatementPayload
from arche_api.domain.enums.canonical_statement_metric import CanonicalStatementMetric
from arche_api.domain.enums.edgar import AccountingStandard, FiscalPeriod, StatementType
from arche_api.domain.services.reconciliation_calendar import (
    classify_fiscal_calendar,
    infer_statement_period,
)


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


def test_infer_statement_period_fy() -> None:
    payload = _payload(
        statement_date=date(2024, 12, 31),
        fiscal_year=2024,
        fiscal_period=FiscalPeriod.FY,
    )

    period = infer_statement_period(payload)
    assert period.period_start.year == 2024
    assert period.period_start.month == 1
    assert period.period_end == date(2024, 12, 31)


def test_classify_fiscal_calendar_standard_year() -> None:
    periods = [
        infer_statement_period(
            _payload(
                statement_date=date(2022, 12, 31),
                fiscal_year=2022,
                fiscal_period=FiscalPeriod.FY,
            )
        ),
        infer_statement_period(
            _payload(
                statement_date=date(2023, 12, 31),
                fiscal_year=2023,
                fiscal_period=FiscalPeriod.FY,
            )
        ),
    ]

    classification = classify_fiscal_calendar(periods)
    assert classification is not None
    assert classification.fye_month == 12
    assert not classification.is_53_week_year
    assert not classification.is_irregular
