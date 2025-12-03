# tests/unit/domain/entities/test_statement_quality.py
# Copyright (c) Stacklion.
# SPDX-License-Identifier: MIT
"""Unit tests for statement quality evaluation domain logic."""

from __future__ import annotations

from datetime import date
from decimal import Decimal

import pytest

from stacklion_api.domain.entities.canonical_statement_payload import CanonicalStatementPayload
from stacklion_api.domain.entities.statement_quality import (
    StatementQualityIssue,
    StatementQualityIssueSeverity,
    StatementQualityReport,
    _check_basic_signs,
    _check_core_metric_presence,
    _check_currency_consistency,
    _check_growth_volatility,
    _compute_score,
    evaluate_statement_quality,
)
from stacklion_api.domain.enums.canonical_statement_metric import CanonicalStatementMetric
from stacklion_api.domain.enums.edgar import FiscalPeriod, StatementType


def _make_payload(
    *,
    statement_type: StatementType = StatementType.INCOME_STATEMENT,
    fiscal_year: int = 2024,
    fiscal_period: FiscalPeriod = FiscalPeriod.Q1,
    currency: str = "USD",
    core_metrics: dict[CanonicalStatementMetric, Decimal] | None = None,
) -> CanonicalStatementPayload:
    """Helper to construct a canonical payload with configurable metrics."""
    return CanonicalStatementPayload(
        cik="0000123456",
        statement_type=statement_type,
        accounting_standard="US_GAAP",
        fiscal_year=fiscal_year,
        fiscal_period=fiscal_period,
        statement_date=date(2024, 3, 31),
        currency=currency,
        unit_multiplier=Decimal("1"),
        source_accession_id="0000123456-24-000001",
        source_taxonomy="us-gaap-2024",
        source_version_sequence=1,
        dimensions={},
        core_metrics=core_metrics or {},
        extra_metrics={},
    )


# --------------------------------------------------------------------------- #
# StatementQualityIssue invariants                                            #
# --------------------------------------------------------------------------- #


def test_statement_quality_issue_invariants() -> None:
    """StatementQualityIssue should enforce non-empty code and dict details."""
    issue = StatementQualityIssue(
        code="TEST",
        message="msg",
        severity=StatementQualityIssueSeverity.INFO,
        details={"k": "v"},
    )
    assert issue.code == "TEST"
    assert issue.details == {"k": "v"}
    assert issue.severity is StatementQualityIssueSeverity.INFO

    # Empty code rejected.
    with pytest.raises(ValueError):
        StatementQualityIssue(
            code="",
            message="msg",
            severity=StatementQualityIssueSeverity.INFO,
            details={},
        )

    # Non-dict details rejected.
    with pytest.raises(ValueError):
        StatementQualityIssue(
            code="X",
            message="msg",
            severity=StatementQualityIssueSeverity.INFO,
            details="not-a-dict",  # type: ignore[arg-type]
        )

    # Wrong severity type rejected.
    with pytest.raises(ValueError):
        StatementQualityIssue(
            code="X",
            message="msg",
            severity="INFO",  # type: ignore[arg-type]
            details={},
        )


# --------------------------------------------------------------------------- #
# StatementQualityReport invariants                                           #
# --------------------------------------------------------------------------- #


def test_statement_quality_report_invariants() -> None:
    """StatementQualityReport enforces score bounds, issues tuple, and types."""
    issue = StatementQualityIssue(
        code="X",
        message="m",
        severity=StatementQualityIssueSeverity.INFO,
        details={},
    )

    # Happy case
    report = StatementQualityReport(
        cik="0000123456",
        statement_type=StatementType.INCOME_STATEMENT,
        fiscal_year=2024,
        fiscal_period="Q1",
        currency="USD",
        issues=(issue,),
        score=Decimal("90"),
        is_modeling_safe=True,
    )
    assert report.score == Decimal("90")
    assert report.issues == (issue,)

    # Score out of bounds rejected.
    with pytest.raises(ValueError):
        StatementQualityReport(
            cik="0000123456",
            statement_type=StatementType.INCOME_STATEMENT,
            fiscal_year=2024,
            fiscal_period="Q1",
            currency="USD",
            issues=(issue,),
            score=Decimal("200"),
            is_modeling_safe=True,
        )

    # issues must be a tuple, not a list.
    with pytest.raises(ValueError):
        StatementQualityReport(
            cik="0000123456",
            statement_type=StatementType.INCOME_STATEMENT,
            fiscal_year=2024,
            fiscal_period="Q1",
            currency="USD",
            issues=[issue],  # type: ignore[arg-type]
            score=Decimal("50"),
            is_modeling_safe=False,
        )

    # issues content must be StatementQualityIssue instances.
    with pytest.raises(ValueError):
        StatementQualityReport(
            cik="0000123456",
            statement_type=StatementType.INCOME_STATEMENT,
            fiscal_year=2024,
            fiscal_period="Q1",
            currency="USD",
            issues=("not-an-issue",),  # type: ignore[arg-type]
            score=Decimal("10"),
            is_modeling_safe=False,
        )

    # statement_type must be a StatementType.
    with pytest.raises(ValueError):
        StatementQualityReport(
            cik="0000123456",
            statement_type="INCOME_STATEMENT",  # type: ignore[arg-type]
            fiscal_year=2024,
            fiscal_period="Q1",
            currency="USD",
            issues=(issue,),
            score=Decimal("10"),
            is_modeling_safe=False,
        )


# --------------------------------------------------------------------------- #
# Core-metric presence and sign checks                                        #
# --------------------------------------------------------------------------- #


def test_check_core_metric_presence_for_income_statement() -> None:
    """Income statement must require REVENUE + NET_INCOME."""
    payload = _make_payload(
        statement_type=StatementType.INCOME_STATEMENT,
        core_metrics={},
    )
    issues = _check_core_metric_presence(payload)
    assert issues
    assert issues[0].code == "MISSING_CORE_METRICS"
    assert "REVENUE" in issues[0].details["missing_metrics"]

    payload_full = _make_payload(
        statement_type=StatementType.INCOME_STATEMENT,
        core_metrics={
            CanonicalStatementMetric.REVENUE: Decimal("100"),
            CanonicalStatementMetric.NET_INCOME: Decimal("10"),
        },
    )
    assert _check_core_metric_presence(payload_full) == []


def test_check_basic_signs_negative_revenue_and_assets() -> None:
    """Negative revenue → WARNING, negative total assets → ERROR."""
    payload = _make_payload(
        statement_type=StatementType.BALANCE_SHEET,
        core_metrics={
            CanonicalStatementMetric.REVENUE: Decimal("-1"),
            CanonicalStatementMetric.TOTAL_ASSETS: Decimal("-5"),
        },
    )
    issues = _check_basic_signs(payload)
    codes = {i.code for i in issues}
    assert "NEGATIVE_REVENUE" in codes
    assert "NEGATIVE_TOTAL_ASSETS" in codes

    severities = {i.code: i.severity for i in issues}
    assert severities["NEGATIVE_REVENUE"] == StatementQualityIssueSeverity.WARNING
    assert severities["NEGATIVE_TOTAL_ASSETS"] == StatementQualityIssueSeverity.ERROR


def test_check_basic_signs_no_issues_when_signs_ok() -> None:
    """No sign issues when revenue/assets are non-negative."""
    payload = _make_payload(
        statement_type=StatementType.BALANCE_SHEET,
        core_metrics={
            CanonicalStatementMetric.REVENUE: Decimal("1"),
            CanonicalStatementMetric.TOTAL_ASSETS: Decimal("5"),
        },
    )
    issues = _check_basic_signs(payload)
    assert issues == []


# --------------------------------------------------------------------------- #
# Currency and volatility rules                                              #
# --------------------------------------------------------------------------- #


def test_currency_consistency_same_currency_no_issue() -> None:
    """_check_currency_consistency should return empty list when currencies match."""
    payload_prev = _make_payload(currency="USD")
    payload_curr = _make_payload(currency="USD")
    issues = _check_currency_consistency(payload_curr, payload_prev)
    assert issues == []


def test_currency_consistency_and_growth_volatility_rules() -> None:
    """Currency mismatch + extreme volatility should both surface via evaluate."""
    prev_payload = _make_payload(
        currency="USD",
        core_metrics={
            CanonicalStatementMetric.REVENUE: Decimal("100"),
            CanonicalStatementMetric.NET_INCOME: Decimal("10"),
        },
    )
    current_payload = _make_payload(
        currency="EUR",
        core_metrics={
            CanonicalStatementMetric.REVENUE: Decimal("400"),  # +300%
            CanonicalStatementMetric.NET_INCOME: Decimal("50"),
        },
    )

    report = evaluate_statement_quality(current_payload, previous_payload=prev_payload)

    codes = {i.code for i in report.issues}
    assert "CURRENCY_MISMATCH" in codes
    assert "EXTREME_VOLATILITY" in codes
    assert report.score < Decimal("100")
    # There is at least one WARNING; score must be reduced, modeling-safe depends on threshold.
    assert report.is_modeling_safe is False or report.score >= Decimal("80")


def test_growth_volatility_threshold_boundary_and_zero_previous() -> None:
    """Volatility rule fires only at >= 200% and ignores previous == 0."""
    prev = _make_payload(
        core_metrics={
            CanonicalStatementMetric.REVENUE: Decimal("100"),
        },
    )
    # 199% change → no issue
    current_near = _make_payload(
        core_metrics={
            CanonicalStatementMetric.REVENUE: Decimal("299"),
        },
    )
    issues_near = _check_growth_volatility(current_near, prev)
    assert not issues_near

    # 200% change → issue
    current_exact = _make_payload(
        core_metrics={
            CanonicalStatementMetric.REVENUE: Decimal("300"),
        },
    )
    issues_exact = _check_growth_volatility(current_exact, prev)
    assert any(i.code == "EXTREME_VOLATILITY" for i in issues_exact)

    # previous == 0 → skip volatility calc safely
    prev_zero = _make_payload(
        core_metrics={
            CanonicalStatementMetric.REVENUE: Decimal("0"),
        },
    )
    current_any = _make_payload(
        core_metrics={
            CanonicalStatementMetric.REVENUE: Decimal("100"),
        },
    )
    issues_zero = _check_growth_volatility(current_any, prev_zero)
    assert issues_zero == []


# --------------------------------------------------------------------------- #
# End-to-end evaluate_statement_quality                                      #
# --------------------------------------------------------------------------- #


def test_evaluate_statement_quality_no_issues_is_perfect_and_safe() -> None:
    """When no rules fire, score should be 100 and modeling_safe True."""
    payload = _make_payload(
        core_metrics={
            CanonicalStatementMetric.REVENUE: Decimal("100"),
            CanonicalStatementMetric.NET_INCOME: Decimal("10"),
        },
    )

    report = evaluate_statement_quality(payload)

    assert report.score == Decimal("100")
    assert report.issues == ()
    assert report.is_modeling_safe is True


def test_evaluate_statement_quality_error_makes_modeling_unsafe() -> None:
    """Any ERROR severity issue should force is_modeling_safe=False."""
    payload = _make_payload(
        statement_type=StatementType.BALANCE_SHEET,
        core_metrics={
            CanonicalStatementMetric.REVENUE: Decimal("10"),
            CanonicalStatementMetric.TOTAL_ASSETS: Decimal("-1"),  # ERROR
        },
    )

    report = evaluate_statement_quality(payload)

    assert any(i.severity is StatementQualityIssueSeverity.ERROR for i in report.issues)
    assert report.is_modeling_safe is False


def test_evaluate_statement_quality_warnings_only_respect_score_threshold() -> None:
    """Warnings only: modeling_safe depends on resulting score."""
    # Build issues manually: 3 warnings -> score 70 -> unsafe.
    issues: list[StatementQualityIssue] = [
        StatementQualityIssue(
            code=f"W{i}",
            message="warn",
            severity=StatementQualityIssueSeverity.WARNING,
            details={},
        )
        for i in range(3)
    ]
    score = _compute_score(issues)
    assert score == Decimal("70")

    report = StatementQualityReport(
        cik="0000123456",
        statement_type=StatementType.INCOME_STATEMENT,
        fiscal_year=2024,
        fiscal_period="Q1",
        currency="USD",
        issues=tuple(issues),
        score=score,
        is_modeling_safe=score >= Decimal("80"),
    )
    assert report.is_modeling_safe is False


# --------------------------------------------------------------------------- #
# _compute_score                                                              #
# --------------------------------------------------------------------------- #


def test_compute_score_respects_severity_weights_and_flooring() -> None:
    """_compute_score should subtract per ERROR/WARNING and floor at 0."""
    info = StatementQualityIssue(
        code="I",
        message="info",
        severity=StatementQualityIssueSeverity.INFO,
        details={},
    )
    warn = StatementQualityIssue(
        code="W",
        message="warn",
        severity=StatementQualityIssueSeverity.WARNING,
        details={},
    )
    err = StatementQualityIssue(
        code="E",
        message="err",
        severity=StatementQualityIssueSeverity.ERROR,
        details={},
    )

    score = _compute_score([info, warn, err])
    # 100 - 10 - 20 = 70
    assert score == Decimal("70")

    many_errs = [err] * 10
    assert _compute_score(many_errs) == Decimal("0")


def test_compute_score_empty_and_info_only_do_not_penalize() -> None:
    """Empty issues and INFO-only issues should not reduce score."""
    assert _compute_score([]) == Decimal("100")

    info_only = [
        StatementQualityIssue(
            code=f"I{i}",
            message="info",
            severity=StatementQualityIssueSeverity.INFO,
            details={},
        )
        for i in range(5)
    ]
    assert _compute_score(info_only) == Decimal("100")
