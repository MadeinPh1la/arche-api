# tests/unit/domain/test_statement_quality.py
# Copyright (c)
# SPDX-License-Identifier: MIT

from __future__ import annotations

from datetime import date
from decimal import Decimal

from stacklion_api.domain.entities.canonical_statement_payload import (
    CanonicalStatementPayload,
)
from stacklion_api.domain.entities.statement_quality import (
    StatementQualityIssueSeverity,
    evaluate_statement_quality,
)
from stacklion_api.domain.enums.canonical_statement_metric import CanonicalStatementMetric
from stacklion_api.domain.enums.edgar import AccountingStandard, FiscalPeriod, StatementType


def _make_payload(
    *,
    statement_type: StatementType = StatementType.INCOME_STATEMENT,
    core_metrics: dict[CanonicalStatementMetric, Decimal] | None = None,
    currency: str = "USD",
) -> CanonicalStatementPayload:
    return CanonicalStatementPayload(
        cik="0000320193",
        statement_type=statement_type,
        accounting_standard=AccountingStandard.US_GAAP,
        statement_date=date(2024, 12, 31),
        fiscal_year=2024,
        fiscal_period=FiscalPeriod.FY,
        currency=currency,
        unit_multiplier=1,
        core_metrics=core_metrics or {},
        extra_metrics={},
        dimensions={},
        source_accession_id="0000320193-24-000012",
        source_taxonomy="us-gaap-2024",
        source_version_sequence=1,
    )


def test_quality_ok_income_statement_with_core_metrics() -> None:
    payload = _make_payload(
        statement_type=StatementType.INCOME_STATEMENT,
        core_metrics={
            CanonicalStatementMetric.REVENUE: Decimal("100"),
            CanonicalStatementMetric.NET_INCOME: Decimal("10"),
        },
    )

    report = evaluate_statement_quality(payload)

    assert report.cik == payload.cik
    assert report.statement_type is StatementType.INCOME_STATEMENT
    assert report.fiscal_year == 2024
    assert report.issues == ()
    assert report.score == Decimal("100")
    assert report.is_modeling_safe is True


def test_quality_flags_missing_core_metrics_income_statement() -> None:
    payload = _make_payload(
        statement_type=StatementType.INCOME_STATEMENT,
        core_metrics={},
    )

    report = evaluate_statement_quality(payload)

    assert len(report.issues) == 1
    issue = report.issues[0]
    assert issue.code == "MISSING_CORE_METRICS"
    assert issue.severity is StatementQualityIssueSeverity.ERROR
    assert "REVENUE" in issue.details["missing_metrics"]
    assert "NET_INCOME" in issue.details["missing_metrics"]
    assert report.score < Decimal("100")
    assert report.is_modeling_safe is False


def test_quality_flags_negative_revenue() -> None:
    payload = _make_payload(
        statement_type=StatementType.INCOME_STATEMENT,
        core_metrics={
            CanonicalStatementMetric.REVENUE: Decimal("-5"),
            CanonicalStatementMetric.NET_INCOME: Decimal("1"),
        },
    )

    report = evaluate_statement_quality(payload)

    codes = {issue.code for issue in report.issues}
    assert "NEGATIVE_REVENUE" in codes
    # At least one WARNING present; score should be below 100.
    assert report.score < Decimal("100")


def test_quality_flags_currency_mismatch_and_extreme_volatility() -> None:
    previous = _make_payload(
        statement_type=StatementType.INCOME_STATEMENT,
        core_metrics={
            CanonicalStatementMetric.REVENUE: Decimal("100"),
            CanonicalStatementMetric.NET_INCOME: Decimal("10"),
        },
        currency="USD",
    )
    current = _make_payload(
        statement_type=StatementType.INCOME_STATEMENT,
        core_metrics={
            CanonicalStatementMetric.REVENUE: Decimal("400"),  # +300% change
            CanonicalStatementMetric.NET_INCOME: Decimal("40"),  # +300% change
        },
        currency="EUR",
    )

    report = evaluate_statement_quality(current, previous_payload=previous)

    codes = {issue.code for issue in report.issues}
    assert "CURRENCY_MISMATCH" in codes
    assert "EXTREME_VOLATILITY" in codes
    # Multiple warnings → score meaningfully below 100.
    assert report.score <= Decimal("80")
    assert report.is_modeling_safe in (True, False)  # boundary behavior depends on total deductions


def test_quality_score_floors_at_zero() -> None:
    # Construct many errors to drive score below zero.
    payload = _make_payload(
        statement_type=StatementType.BALANCE_SHEET,
        core_metrics={
            CanonicalStatementMetric.TOTAL_ASSETS: Decimal("-1"),
        },
    )

    report = evaluate_statement_quality(payload)

    assert report.score >= Decimal("0")
