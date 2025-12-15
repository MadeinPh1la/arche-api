# src/arche_api/domain/entities/statement_quality.py
# Copyright (c)
# SPDX-License-Identifier: MIT
"""Statement quality evaluation.

Purpose:
    Provide a Bloomberg-class, deterministic quality evaluation for normalized
    canonical financial statements. The goal is to surface issues that affect
    modeling trustworthiness (missing metrics, sign problems, excessive
    volatility, currency inconsistencies) in a structured, machine-readable
    form.

Layer:
    domain

Notes:
    - Pure domain logic only (no logging, no HTTP, no persistence).
    - All numeric values are :class:`decimal.Decimal`.
    - Thresholds are intentionally conservative; callers may apply further
      interpretation.
"""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass
from decimal import Decimal
from enum import Enum
from typing import Any

from arche_api.domain.entities.canonical_statement_payload import CanonicalStatementPayload
from arche_api.domain.enums.canonical_statement_metric import CanonicalStatementMetric
from arche_api.domain.enums.edgar import StatementType


class StatementQualityIssueSeverity(str, Enum):
    """Severity classification for statement quality issues.

    Attributes:
        INFO: Informational note; does not affect score.
        WARNING: Issue that may affect modeling; reduces score moderately.
        ERROR: Severe issue affecting modeling trustworthiness.
    """

    INFO = "INFO"
    WARNING = "WARNING"
    ERROR = "ERROR"


@dataclass(frozen=True)
class StatementQualityIssue:
    """Single quality issue detected on a statement.

    Attributes:
        code: Machine-readable issue code.
        message: Human-readable explanation.
        severity: Issue severity level.
        details: Arbitrary key-value diagnostic information.
    """

    code: str
    message: str
    severity: StatementQualityIssueSeverity
    details: dict[str, Any]

    def __post_init__(self) -> None:
        """Enforce basic invariants."""
        if not self.code:
            raise ValueError("Issue code must be non-empty.")
        if not isinstance(self.details, dict):
            raise ValueError("details must be a dict.")
        if not isinstance(self.severity, StatementQualityIssueSeverity):
            raise ValueError("severity must be a StatementQualityIssueSeverity.")


@dataclass(frozen=True)
class StatementQualityReport:
    """Aggregated quality report for a canonical statement payload.

    Attributes:
        cik: Company CIK.
        statement_type: Statement type (income, balance sheet, etc.).
        fiscal_year: Fiscal year.
        fiscal_period: Fiscal period of the statement.
        currency: Currency of the statement.
        issues: Tuple of all detected issues.
        score: Quality score between 0 and 100.
        is_modeling_safe: Indicates whether this statement is safe for modeling.
    """

    cik: str
    statement_type: StatementType
    fiscal_year: int
    fiscal_period: str
    currency: str
    issues: tuple[StatementQualityIssue, ...]
    score: Decimal
    is_modeling_safe: bool

    def __post_init__(self) -> None:
        """Enforce invariants for integrity."""
        if not (Decimal("0") <= self.score <= Decimal("100")):
            raise ValueError("score must be between 0 and 100.")
        if not isinstance(self.issues, tuple):
            raise ValueError("issues must be a tuple.")
        for issue in self.issues:
            if not isinstance(issue, StatementQualityIssue):
                raise ValueError("issues must contain only StatementQualityIssue objects.")
        if not isinstance(self.is_modeling_safe, bool):
            raise ValueError("is_modeling_safe must be a boolean.")
        if not isinstance(self.statement_type, StatementType):
            raise ValueError("statement_type must be a StatementType.")


# --------------------------------------------------------------------------- #
# Core evaluation entrypoint                                                 #
# --------------------------------------------------------------------------- #


def evaluate_statement_quality(
    payload: CanonicalStatementPayload,
    *,
    previous_payload: CanonicalStatementPayload | None = None,
) -> StatementQualityReport:
    """Evaluate the quality of a normalized canonical statement.

    The evaluation applies deterministic rules:

    * Presence of core metrics expected for the statement type.
    * Basic sign sanity checks (e.g., non-negative revenue).
    * Currency consistency when comparing with a previous payload.
    * Extreme period-over-period volatility checks.

    Args:
        payload: Target canonical statement payload.
        previous_payload: Optional prior-period payload used for comparing
            currency consistency and volatility.

    Returns:
        A StatementQualityReport with all detected issues and a 0–100 score.
    """
    issues: list[StatementQualityIssue] = []

    # Core rules:
    issues.extend(_check_core_metric_presence(payload))
    issues.extend(_check_basic_signs(payload))

    # Comparative rules:
    if previous_payload is not None:
        issues.extend(_check_currency_consistency(payload, previous_payload))
        issues.extend(_check_growth_volatility(payload, previous_payload))

    score = _compute_score(issues)

    # Modeling safety rules:
    #   - Any ERROR → unsafe.
    #   - No ERROR, only WARNING → require score >= 80.
    has_error = any(issue.severity is StatementQualityIssueSeverity.ERROR for issue in issues)
    is_modeling_safe = False if has_error else score >= Decimal("80")

    return StatementQualityReport(
        cik=payload.cik,
        statement_type=payload.statement_type,
        fiscal_year=payload.fiscal_year,
        fiscal_period=payload.fiscal_period.value,
        currency=payload.currency,
        issues=tuple(issues),
        score=score,
        is_modeling_safe=is_modeling_safe,
    )


# --------------------------------------------------------------------------- #
# Rule implementations                                                       #
# --------------------------------------------------------------------------- #


def _check_core_metric_presence(payload: CanonicalStatementPayload) -> list[StatementQualityIssue]:
    """Check for missing core metrics by statement type.

    Args:
        payload: Canonical statement payload.

    Returns:
        A list of StatementQualityIssue describing missing core metrics.
    """
    metrics = payload.core_metrics
    st = payload.statement_type

    required_metrics: Iterable[CanonicalStatementMetric]

    if st is StatementType.INCOME_STATEMENT:
        required_metrics = (
            CanonicalStatementMetric.REVENUE,
            CanonicalStatementMetric.NET_INCOME,
        )
    elif st is StatementType.BALANCE_SHEET:
        required_metrics = (
            CanonicalStatementMetric.TOTAL_ASSETS,
            CanonicalStatementMetric.TOTAL_LIABILITIES,
            CanonicalStatementMetric.TOTAL_EQUITY,
        )
    elif st is StatementType.CASH_FLOW_STATEMENT:
        required_metrics = (
            CanonicalStatementMetric.NET_CASH_FROM_OPERATING_ACTIVITIES,
            CanonicalStatementMetric.NET_CASH_FROM_FINANCING_ACTIVITIES,
            CanonicalStatementMetric.NET_CASH_FROM_INVESTING_ACTIVITIES,
        )
    else:
        return []

    missing = [m for m in required_metrics if m not in metrics]
    if not missing:
        return []

    return [
        StatementQualityIssue(
            code="MISSING_CORE_METRICS",
            message="Missing core metrics for statement type.",
            severity=StatementQualityIssueSeverity.ERROR,
            details={
                "statement_type": st.value,
                "missing_metrics": [m.value for m in missing],
            },
        )
    ]


def _check_basic_signs(payload: CanonicalStatementPayload) -> list[StatementQualityIssue]:
    """Check basic sign sanity for selected metrics.

    Args:
        payload: Canonical statement payload.

    Returns:
        A list of StatementQualityIssue describing sign inconsistencies.
    """
    issues: list[StatementQualityIssue] = []
    metrics = payload.core_metrics

    revenue = metrics.get(CanonicalStatementMetric.REVENUE)
    if revenue is not None and revenue < Decimal("0"):
        issues.append(
            StatementQualityIssue(
                code="NEGATIVE_REVENUE",
                message="Revenue is negative, which is usually a data issue.",
                severity=StatementQualityIssueSeverity.WARNING,
                details={"revenue": str(revenue)},
            )
        )

    total_assets = metrics.get(CanonicalStatementMetric.TOTAL_ASSETS)
    if total_assets is not None and total_assets < Decimal("0"):
        issues.append(
            StatementQualityIssue(
                code="NEGATIVE_TOTAL_ASSETS",
                message="Total assets is negative, which is usually a data issue.",
                severity=StatementQualityIssueSeverity.ERROR,
                details={"total_assets": str(total_assets)},
            )
        )

    return issues


def _check_currency_consistency(
    payload: CanonicalStatementPayload,
    previous_payload: CanonicalStatementPayload,
) -> list[StatementQualityIssue]:
    """Ensure currency consistency with the previous payload.

    Args:
        payload: Current canonical statement payload.
        previous_payload: Previous canonical statement payload.

    Returns:
        A list with one warning if currencies differ, otherwise empty.
    """
    if payload.currency == previous_payload.currency:
        return []

    return [
        StatementQualityIssue(
            code="CURRENCY_MISMATCH",
            message="Currency differs from previous-period statement.",
            severity=StatementQualityIssueSeverity.WARNING,
            details={
                "current_currency": payload.currency,
                "previous_currency": previous_payload.currency,
            },
        )
    ]


def _check_growth_volatility(
    payload: CanonicalStatementPayload,
    previous_payload: CanonicalStatementPayload,
) -> list[StatementQualityIssue]:
    """Detect extreme period-over-period volatility in selected metrics.

    Args:
        payload: Current canonical statement payload.
        previous_payload: Prior-period canonical statement payload.

    Returns:
        A list of StatementQualityIssue indicating extreme volatility.
    """
    issues: list[StatementQualityIssue] = []
    current_metrics = payload.core_metrics
    prev_metrics = previous_payload.core_metrics

    for metric in (
        CanonicalStatementMetric.REVENUE,
        CanonicalStatementMetric.NET_INCOME,
    ):
        current = current_metrics.get(metric)
        previous = prev_metrics.get(metric)
        if current is None or previous is None:
            continue
        if previous == Decimal("0"):
            continue

        change = (current - previous) / previous

        # Extreme volatility threshold: 200%+ absolute change
        if change.copy_abs() >= Decimal("2"):
            issues.append(
                StatementQualityIssue(
                    code="EXTREME_VOLATILITY",
                    message="Metric exhibits extreme period-over-period change.",
                    severity=StatementQualityIssueSeverity.WARNING,
                    details={
                        "metric": metric.value,
                        "previous": str(previous),
                        "current": str(current),
                        "change_ratio": str(change),
                    },
                )
            )

    return issues


def _compute_score(issues: Iterable[StatementQualityIssue]) -> Decimal:
    """Compute a 0–100 quality score from issue severities.

    Strategy:
        - Start from 100.
        - Subtract 20 points for each ERROR.
        - Subtract 10 points for each WARNING.
        - INFO does not affect the score.
        - Floor at 0.
    """
    score = Decimal("100")

    for issue in issues:
        if issue.severity is StatementQualityIssueSeverity.ERROR:
            score -= Decimal("20")
        elif issue.severity is StatementQualityIssueSeverity.WARNING:
            score -= Decimal("10")

    return max(score, Decimal("0"))
