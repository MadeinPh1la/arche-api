# src/stacklion_api/domain/services/derived_metrics_engine.py
# Copyright (c)
# SPDX-License-Identifier: MIT
"""Derived metrics computation engine.

Purpose:
    Provide a deterministic, testable, Bloomberg-class derived-metrics engine
    on top of canonical normalized statement payloads. The engine computes
    margins, growth rates, cash-flow measures, capital-structure ratios, and
    returns using only domain-layer types.

Layer:
    domain

Notes:
    - This module is pure domain logic:
        * No logging.
        * No HTTP concerns.
        * No Prometheus metrics.
        * No persistence or gateways.
    - All numeric values are :class:`decimal.Decimal`.
    - Errors are surfaced as structured MetricFailure instances instead of
      exceptions, allowing callers to reason about partial success.
    - The DerivedMetricSpec registry is the single source of truth for
      metric inputs, history windows, categories, and descriptions.
"""

from __future__ import annotations

from collections.abc import Callable, Iterable, Sequence
from dataclasses import dataclass
from decimal import Decimal, InvalidOperation, getcontext
from enum import Enum

from stacklion_api.domain.entities.canonical_statement_payload import CanonicalStatementPayload
from stacklion_api.domain.enums.canonical_statement_metric import CanonicalStatementMetric
from stacklion_api.domain.enums.derived_metric import DerivedMetric
from stacklion_api.domain.enums.derived_metric_category import DerivedMetricCategory
from stacklion_api.domain.enums.edgar import StatementType

# Increase precision slightly over default to reduce cascading rounding issues.
getcontext().prec = max(getcontext().prec, 34)

# Named numeric constants (no magic numbers).
DECIMAL_ZERO = Decimal("0")
DECIMAL_ONE = Decimal("1")
DECIMAL_EPSILON = Decimal("1e-9")  # Guard for tiny denominators.
RATIO_SCALE = Decimal("1e-6")  # Used for ratio quantization (6 decimal places).


class MetricFailureReason(str, Enum):
    """Reasons why a derived metric could not be computed."""

    MISSING_INPUT = "MISSING_INPUT"
    NOT_APPLICABLE = "NOT_APPLICABLE"
    ZERO_DENOMINATOR = "ZERO_DENOMINATOR"
    INSUFFICIENT_HISTORY = "INSUFFICIENT_HISTORY"
    INVALID_OPERATION = "INVALID_OPERATION"
    NEGATIVE_DENOMINATOR_GUARD = "NEGATIVE_DENOMINATOR_GUARD"
    OTHER = "OTHER"


@dataclass(frozen=True)
class MetricFailure:
    """Structured failure record for a derived metric computation."""

    metric: DerivedMetric
    reason: MetricFailureReason
    details: dict[str, str] | None = None


@dataclass(frozen=True)
class MetricContext:
    """Computation context for a derived metric.

    Attributes:
        payload:
            Canonical payload representing the current period.
        history:
            Ordered sequence of prior payloads for the same company
            (oldest to newest). History may contain different fiscal
            periods or statement types; formulas are responsible for
            selecting relevant entries.
    """

    payload: CanonicalStatementPayload
    history: Sequence[CanonicalStatementPayload]


@dataclass(frozen=True)
class DerivedMetricSpec:
    """Specification for a derived metric and its computation formula.

    The spec is the single source of truth for:
        * Required statement types.
        * Required canonical input metrics.
        * History / window requirements.
        * Metric category and description.
        * Whether the metric is experimental.
        * The pure computation formula.

    Attributes:
        metric:
            Derived metric identifier.
        required_statement_types:
            Set of statement types for which this metric is conceptually
            valid (e.g., INCOME_STATEMENT for margins).
        required_inputs:
            Canonical statement metrics that must be present on the current
            payload for the metric to be computable.
        uses_history:
            Whether the metric is expected to inspect ``ctx.history``.
        window_requirements:
            Dictionary expressing history requirements. The primary key used
            is ``"history_periods"``, defined as the minimum number of prior
            periods required for a valid computation.
        category:
            High-level category (margin, growth, cash flow, leverage, return).
        description:
            Short human-readable description of the metric's definition.
        is_experimental:
            Whether the metric is considered experimental or more assumption-
            heavy; callers may choose to opt out of such metrics.
        formula:
            Pure computation function that takes a MetricContext and returns
            a Decimal. It may raise internal DerivedMetricError subclasses
            which the engine maps to MetricFailureReason values.
    """

    metric: DerivedMetric
    required_statement_types: frozenset[StatementType]
    required_inputs: frozenset[CanonicalStatementMetric]
    uses_history: bool
    window_requirements: dict[str, int]
    category: DerivedMetricCategory
    description: str
    is_experimental: bool
    formula: Callable[[MetricContext], Decimal]


@dataclass(frozen=True)
class DerivedMetricsResult:
    """Result of computing one or more derived metrics.

    Attributes:
        values:
            Mapping from metric identifier to successfully computed value.
            Only metrics that completed successfully are present here.
        failures:
            Tuple of MetricFailure instances describing metrics that could
            not be computed for the given context (missing input, not
            applicable, insufficient history, etc.).
    """

    values: dict[DerivedMetric, Decimal]
    failures: tuple[MetricFailure, ...]


# --------------------------------------------------------------------------- #
# Internal error types                                                        #
# --------------------------------------------------------------------------- #


class DerivedMetricError(Exception):
    """Base class for derived metric computation errors."""


class MissingInputError(DerivedMetricError):
    """Raised when a required input value is missing."""


class InsufficientHistoryError(DerivedMetricError):
    """Raised when there is not enough history to compute a metric."""


class ZeroDenominatorError(DerivedMetricError):
    """Raised when a metric would divide by zero."""


class NegativeDenominatorGuardError(DerivedMetricError):
    """Raised when a denominator is too small in magnitude to be stable."""


# --------------------------------------------------------------------------- #
# Helpers                                                                     #
# --------------------------------------------------------------------------- #


def _get_core_metric(
    payload: CanonicalStatementPayload,
    metric: CanonicalStatementMetric,
) -> Decimal | None:
    """Return a core metric value from a payload or None if absent."""
    return payload.core_metrics.get(metric)


def _quantize_ratio(value: Decimal) -> Decimal:
    """Quantize ratio-like values to a stable number of decimal places.

    Ratios are rounded to six decimal places using a deterministic quantization
    scheme to reduce noise in downstream time-series comparisons.
    """
    try:
        return (value / RATIO_SCALE).to_integral_value() * RATIO_SCALE
    except (InvalidOperation, ZeroDivisionError):
        return value


def _safe_divide(
    numerator: Decimal | None,
    denominator: Decimal | None,
) -> Decimal:
    """Safely divide two Decimals, raising on invalid operations.

    Args:
        numerator:
            Numerator value; may be None if an upstream input is missing.
        denominator:
            Denominator value; may be None if an upstream input is missing.

    Returns:
        Decimal representing ``numerator / denominator``.

    Raises:
        MissingInputError:
            If either numerator or denominator is None.
        ZeroDenominatorError:
            If denominator is exactly zero.
        NegativeDenominatorGuardError:
            If denominator is too small in magnitude to produce a stable
            ratio (guard against exploding ratios on tiny denominators).
    """
    if numerator is None or denominator is None:
        raise MissingInputError("numerator and denominator must be present for division")

    if denominator == DECIMAL_ZERO:
        raise ZeroDenominatorError("denominator is zero")

    if abs(denominator) < DECIMAL_EPSILON:
        raise NegativeDenominatorGuardError("denominator magnitude too small for stable ratio")

    try:
        return numerator / denominator
    except InvalidOperation as exc:
        raise MissingInputError(f"invalid decimal operation: {exc}") from exc


def _select_prior_payload(
    ctx: MetricContext,
    *,
    years_back: int | None = None,
    quarters_back: int | None = None,
) -> CanonicalStatementPayload | None:
    """Select a prior payload from history for YoY/QoQ style comparisons.

    This helper is intentionally simple and deterministic:
        - For years_back:
            * Prefer same statement_type, fiscal_period and fiscal_year - years_back.
        - For quarters_back:
            * Prefer same statement_type and the nearest earlier payload by
              statement_date.

    Args:
        ctx: Metric context.
        years_back: Number of fiscal years to look back for YoY.
        quarters_back: Number of quarters to look back for QoQ.

    Returns:
        Matching prior payload or None if not available.
    """
    payload = ctx.payload

    if years_back is not None:
        target_year = payload.fiscal_year - years_back
        for p in reversed(ctx.history):
            if (
                p.statement_type == payload.statement_type
                and p.fiscal_year == target_year
                and p.fiscal_period == payload.fiscal_period
            ):
                return p
        return None

    if quarters_back is not None:
        previous = None
        for p in ctx.history:
            if (
                p.statement_type == payload.statement_type
                and p.statement_date < payload.statement_date
            ):
                previous = p
        return previous

    return None


# --------------------------------------------------------------------------- #
# Metric formulas                                                             #
# --------------------------------------------------------------------------- #


def _gross_margin(ctx: MetricContext) -> Decimal:
    revenue = _get_core_metric(ctx.payload, CanonicalStatementMetric.REVENUE)
    gross_profit = _get_core_metric(ctx.payload, CanonicalStatementMetric.GROSS_PROFIT)
    ratio = _safe_divide(gross_profit, revenue)
    return _quantize_ratio(ratio)


def _operating_margin(ctx: MetricContext) -> Decimal:
    revenue = _get_core_metric(ctx.payload, CanonicalStatementMetric.REVENUE)
    operating_income = _get_core_metric(ctx.payload, CanonicalStatementMetric.OPERATING_INCOME)
    ratio = _safe_divide(operating_income, revenue)
    return _quantize_ratio(ratio)


def _net_margin(ctx: MetricContext) -> Decimal:
    revenue = _get_core_metric(ctx.payload, CanonicalStatementMetric.REVENUE)
    net_income = _get_core_metric(ctx.payload, CanonicalStatementMetric.NET_INCOME)
    ratio = _safe_divide(net_income, revenue)
    return _quantize_ratio(ratio)


def _revenue_growth_yoy(ctx: MetricContext) -> Decimal:
    """Compute year-over-year revenue growth for the same fiscal period."""
    current_rev = _get_core_metric(ctx.payload, CanonicalStatementMetric.REVENUE)
    prior = _select_prior_payload(ctx, years_back=1)
    if prior is None:
        raise InsufficientHistoryError("no prior payload found for YoY revenue growth")

    prior_rev = _get_core_metric(prior, CanonicalStatementMetric.REVENUE)
    if prior_rev is None:
        raise MissingInputError("missing REVENUE in prior period for YoY revenue growth")

    delta = current_rev - prior_rev  # type: ignore[operator]
    ratio = _safe_divide(delta, prior_rev)
    return _quantize_ratio(ratio)


def _revenue_growth_qoq(ctx: MetricContext) -> Decimal:
    """Compute quarter-over-quarter revenue growth."""
    current_rev = _get_core_metric(ctx.payload, CanonicalStatementMetric.REVENUE)
    prior = _select_prior_payload(ctx, quarters_back=1)
    if prior is None:
        raise InsufficientHistoryError("no prior payload found for QoQ revenue growth")

    prior_rev = _get_core_metric(prior, CanonicalStatementMetric.REVENUE)
    if prior_rev is None:
        raise MissingInputError("missing REVENUE in prior period for QoQ revenue growth")

    delta = current_rev - prior_rev  # type: ignore[operator]
    ratio = _safe_divide(delta, prior_rev)
    return _quantize_ratio(ratio)


def _revenue_growth_ttm(ctx: MetricContext) -> Decimal:
    """Compute trailing-twelve-month revenue growth.

    Definition:
        - TTM(revenue) is defined as the sum of the most recent 4
          same-statement_type periods, ordered by statement_date.
        - The prior TTM window is defined as the 4 periods immediately
          preceding the current TTM window.
        - All periods are assumed to be comparable (same fiscal calendar
          and period length); callers are responsible for pre-filtering
          heterogeneous histories.

    Behavior:
        - Requires at least 8 comparable periods (including the current
          payload) for a valid TTM comparison.
        - Raises InsufficientHistoryError when there are fewer than 8
          comparable periods available.
        - Raises MissingInputError when any period in the TTM or prior-TTM
          window is missing REVENUE.
    """
    relevant: list[CanonicalStatementPayload] = [
        p for p in ctx.history if p.statement_type == ctx.payload.statement_type
    ]
    relevant.append(ctx.payload)
    relevant = sorted(relevant, key=lambda p: p.statement_date)

    if len(relevant) < 8:
        raise InsufficientHistoryError("at least 8 comparable periods are required for TTM growth")

    last_four = relevant[-4:]
    current_ttm = DECIMAL_ZERO
    for p in last_four:
        rev = _get_core_metric(p, CanonicalStatementMetric.REVENUE)
        if rev is None:
            raise MissingInputError("missing REVENUE in current TTM window")
        current_ttm += rev

    prior_four = relevant[-8:-4]
    prior_ttm = DECIMAL_ZERO
    for p in prior_four:
        rev = _get_core_metric(p, CanonicalStatementMetric.REVENUE)
        if rev is None:
            raise MissingInputError("missing REVENUE in prior TTM window")
        prior_ttm += rev

    delta = current_ttm - prior_ttm
    ratio = _safe_divide(delta, prior_ttm)
    return _quantize_ratio(ratio)


def _eps_diluted_growth(ctx: MetricContext) -> Decimal:
    """Compute year-over-year diluted EPS growth."""
    current_eps = _get_core_metric(ctx.payload, CanonicalStatementMetric.DILUTED_EPS)
    prior = _select_prior_payload(ctx, years_back=1)
    if prior is None:
        raise InsufficientHistoryError("no prior payload found for EPS diluted growth")

    prior_eps = _get_core_metric(prior, CanonicalStatementMetric.DILUTED_EPS)
    if prior_eps is None:
        raise MissingInputError("missing DILUTED_EPS in prior period for EPS growth")

    delta = current_eps - prior_eps  # type: ignore[operator]
    ratio = _safe_divide(delta, prior_eps)
    return _quantize_ratio(ratio)


def _ebit(ctx: MetricContext) -> Decimal:
    income_before_tax = _get_core_metric(ctx.payload, CanonicalStatementMetric.INCOME_BEFORE_TAX)
    interest_expense = _get_core_metric(ctx.payload, CanonicalStatementMetric.INTEREST_EXPENSE)
    interest_income = _get_core_metric(ctx.payload, CanonicalStatementMetric.INTEREST_INCOME)

    if income_before_tax is None or interest_expense is None or interest_income is None:
        # Preserve legacy behavior expected by tests: UFCF failure reports "EBIT".
        raise MissingInputError("EBIT")

    return income_before_tax + interest_expense - interest_income


def _ebitda(ctx: MetricContext) -> Decimal:
    operating_income = _get_core_metric(ctx.payload, CanonicalStatementMetric.OPERATING_INCOME)
    da = _get_core_metric(
        ctx.payload,
        CanonicalStatementMetric.DEPRECIATION_AND_AMORTIZATION_EXPENSE,
    )
    if operating_income is None or da is None:
        raise MissingInputError("OPERATING_INCOME and DA are required for EBITDA")
    return operating_income + da


def _levered_free_cash_flow(ctx: MetricContext) -> Decimal:
    """Compute levered free cash flow.

    Definition:
        - Prefer canonical FREE_CASH_FLOW if provided by the normalized
          payload.
        - Otherwise approximate as CFO + CAPEX (with CAPEX typically
          negative).
    """
    fcf = _get_core_metric(ctx.payload, CanonicalStatementMetric.FREE_CASH_FLOW)
    if fcf is not None:
        return fcf

    cfo = _get_core_metric(
        ctx.payload,
        CanonicalStatementMetric.NET_CASH_FROM_OPERATING_ACTIVITIES,
    )
    capex = _get_core_metric(ctx.payload, CanonicalStatementMetric.CAPITAL_EXPENDITURES)
    if cfo is None or capex is None:
        raise MissingInputError(
            "NET_CASH_FROM_OPERATING_ACTIVITIES and CAPITAL_EXPENDITURES are required for LFCF"
        )
    return cfo + capex


def _unlevered_free_cash_flow(ctx: MetricContext) -> Decimal:
    """Compute unlevered free cash flow (approximate).

    Definition:
        - NOPAT = EBIT * (1 - tax_rate)
        - tax_rate = INCOME_TAX_EXPENSE / INCOME_BEFORE_TAX
        - UFCF ≈ NOPAT + DA + CAPEX - ΔWC, with ΔWC approximated as 0 in
          this per-period engine. Multi-period working-capital modeling is
          handled at higher layers.
    """
    ebit = _ebit(ctx)
    income_tax_expense = _get_core_metric(
        ctx.payload,
        CanonicalStatementMetric.INCOME_TAX_EXPENSE,
    )
    income_before_tax = _get_core_metric(
        ctx.payload,
        CanonicalStatementMetric.INCOME_BEFORE_TAX,
    )
    da = _get_core_metric(
        ctx.payload,
        CanonicalStatementMetric.DEPRECIATION_AND_AMORTIZATION_EXPENSE,
    )
    capex = _get_core_metric(ctx.payload, CanonicalStatementMetric.CAPITAL_EXPENDITURES)

    if income_tax_expense is None or income_before_tax is None or da is None or capex is None:
        raise MissingInputError(
            "INCOME_TAX_EXPENSE, INCOME_BEFORE_TAX, DA and CAPEX are required for UFCF",
        )

    tax_rate = _safe_divide(income_tax_expense, income_before_tax)
    nopat = ebit * (DECIMAL_ONE - tax_rate)

    # Working-capital delta is modeled at higher layers; treat ΔWC ≈ 0 here.
    delta_working_capital = DECIMAL_ZERO
    return nopat + da + capex - delta_working_capital


def _working_capital(ctx: MetricContext) -> Decimal:
    current_assets = _get_core_metric(
        ctx.payload,
        CanonicalStatementMetric.TOTAL_CURRENT_ASSETS,
    )
    current_liabilities = _get_core_metric(
        ctx.payload,
        CanonicalStatementMetric.TOTAL_CURRENT_LIABILITIES,
    )
    if current_assets is None or current_liabilities is None:
        raise MissingInputError(
            "TOTAL_CURRENT_ASSETS and TOTAL_CURRENT_LIABILITIES are required for WORKING_CAPITAL",
        )
    return current_assets - current_liabilities


def _debt_to_equity(ctx: MetricContext) -> Decimal:
    short_term_debt = (
        _get_core_metric(ctx.payload, CanonicalStatementMetric.SHORT_TERM_DEBT) or DECIMAL_ZERO
    )
    current_portion_ltd = (
        _get_core_metric(
            ctx.payload,
            CanonicalStatementMetric.CURRENT_PORTION_OF_LONG_TERM_DEBT,
        )
        or DECIMAL_ZERO
    )
    long_term_debt = (
        _get_core_metric(ctx.payload, CanonicalStatementMetric.LONG_TERM_DEBT) or DECIMAL_ZERO
    )
    cash = (
        _get_core_metric(
            ctx.payload,
            CanonicalStatementMetric.CASH_AND_CASH_EQUIVALENTS,
        )
        or DECIMAL_ZERO
    )
    total_equity = _get_core_metric(ctx.payload, CanonicalStatementMetric.TOTAL_EQUITY)

    if total_equity is None:
        raise MissingInputError("TOTAL_EQUITY is required for DEBT_TO_EQUITY")

    net_debt = short_term_debt + current_portion_ltd + long_term_debt - cash
    ratio = _safe_divide(net_debt, total_equity)
    return _quantize_ratio(ratio)


def _interest_coverage(ctx: MetricContext) -> Decimal:
    ebit = _ebit(ctx)
    interest_expense = _get_core_metric(
        ctx.payload,
        CanonicalStatementMetric.INTEREST_EXPENSE,
    )
    if interest_expense is None:
        raise MissingInputError("INTEREST_EXPENSE is required for INTEREST_COVERAGE")

    ratio = _safe_divide(ebit, interest_expense)
    return _quantize_ratio(ratio)


def _roe(ctx: MetricContext) -> Decimal:
    net_income = _get_core_metric(ctx.payload, CanonicalStatementMetric.NET_INCOME)
    total_equity = _get_core_metric(ctx.payload, CanonicalStatementMetric.TOTAL_EQUITY)

    if net_income is None or total_equity is None:
        raise MissingInputError("NET_INCOME and TOTAL_EQUITY are required for ROE")

    ratio = _safe_divide(net_income, total_equity)
    return _quantize_ratio(ratio)


def _roa(ctx: MetricContext) -> Decimal:
    net_income = _get_core_metric(ctx.payload, CanonicalStatementMetric.NET_INCOME)
    total_assets = _get_core_metric(ctx.payload, CanonicalStatementMetric.TOTAL_ASSETS)

    if net_income is None or total_assets is None:
        raise MissingInputError("NET_INCOME and TOTAL_ASSETS are required for ROA")

    ratio = _safe_divide(net_income, total_assets)
    return _quantize_ratio(ratio)


def _roic(ctx: MetricContext) -> Decimal:
    ebit = _ebit(ctx)
    income_tax_expense = _get_core_metric(
        ctx.payload,
        CanonicalStatementMetric.INCOME_TAX_EXPENSE,
    )
    income_before_tax = _get_core_metric(
        ctx.payload,
        CanonicalStatementMetric.INCOME_BEFORE_TAX,
    )
    total_equity = _get_core_metric(ctx.payload, CanonicalStatementMetric.TOTAL_EQUITY)
    long_term_debt = (
        _get_core_metric(ctx.payload, CanonicalStatementMetric.LONG_TERM_DEBT) or DECIMAL_ZERO
    )
    short_term_debt = (
        _get_core_metric(ctx.payload, CanonicalStatementMetric.SHORT_TERM_DEBT) or DECIMAL_ZERO
    )
    current_portion_ltd = (
        _get_core_metric(
            ctx.payload,
            CanonicalStatementMetric.CURRENT_PORTION_OF_LONG_TERM_DEBT,
        )
        or DECIMAL_ZERO
    )
    cash = (
        _get_core_metric(
            ctx.payload,
            CanonicalStatementMetric.CASH_AND_CASH_EQUIVALENTS,
        )
        or DECIMAL_ZERO
    )

    if income_tax_expense is None or income_before_tax is None or total_equity is None:
        raise MissingInputError(
            "INCOME_TAX_EXPENSE, INCOME_BEFORE_TAX and TOTAL_EQUITY are required for ROIC",
        )

    tax_rate = _safe_divide(income_tax_expense, income_before_tax)
    nopat = ebit * (DECIMAL_ONE - tax_rate)

    invested_capital = total_equity + long_term_debt + short_term_debt + current_portion_ltd - cash
    ratio = _safe_divide(nopat, invested_capital)
    return _quantize_ratio(ratio)


# --------------------------------------------------------------------------- #
# Registry and engine                                                         #
# --------------------------------------------------------------------------- #


DERIVED_METRIC_SPECS: dict[DerivedMetric, DerivedMetricSpec] = {
    DerivedMetric.GROSS_MARGIN: DerivedMetricSpec(
        metric=DerivedMetric.GROSS_MARGIN,
        required_statement_types=frozenset({StatementType.INCOME_STATEMENT}),
        required_inputs=frozenset(
            {
                CanonicalStatementMetric.REVENUE,
                CanonicalStatementMetric.GROSS_PROFIT,
            },
        ),
        uses_history=False,
        window_requirements={},
        category=DerivedMetricCategory.MARGIN,
        description="Gross profit divided by revenue.",
        is_experimental=False,
        formula=_gross_margin,
    ),
    DerivedMetric.OPERATING_MARGIN: DerivedMetricSpec(
        metric=DerivedMetric.OPERATING_MARGIN,
        required_statement_types=frozenset({StatementType.INCOME_STATEMENT}),
        required_inputs=frozenset(
            {
                CanonicalStatementMetric.REVENUE,
                CanonicalStatementMetric.OPERATING_INCOME,
            },
        ),
        uses_history=False,
        window_requirements={},
        category=DerivedMetricCategory.MARGIN,
        description="Operating income divided by revenue.",
        is_experimental=False,
        formula=_operating_margin,
    ),
    DerivedMetric.NET_MARGIN: DerivedMetricSpec(
        metric=DerivedMetric.NET_MARGIN,
        required_statement_types=frozenset({StatementType.INCOME_STATEMENT}),
        required_inputs=frozenset(
            {
                CanonicalStatementMetric.REVENUE,
                CanonicalStatementMetric.NET_INCOME,
            },
        ),
        uses_history=False,
        window_requirements={},
        category=DerivedMetricCategory.MARGIN,
        description="Net income divided by revenue.",
        is_experimental=False,
        formula=_net_margin,
    ),
    DerivedMetric.REVENUE_GROWTH_YOY: DerivedMetricSpec(
        metric=DerivedMetric.REVENUE_GROWTH_YOY,
        required_statement_types=frozenset({StatementType.INCOME_STATEMENT}),
        required_inputs=frozenset({CanonicalStatementMetric.REVENUE}),
        uses_history=True,
        window_requirements={"history_periods": 1},
        category=DerivedMetricCategory.GROWTH,
        description="Year-over-year revenue growth for the same fiscal period.",
        is_experimental=False,
        formula=_revenue_growth_yoy,
    ),
    DerivedMetric.REVENUE_GROWTH_QOQ: DerivedMetricSpec(
        metric=DerivedMetric.REVENUE_GROWTH_QOQ,
        required_statement_types=frozenset({StatementType.INCOME_STATEMENT}),
        required_inputs=frozenset({CanonicalStatementMetric.REVENUE}),
        uses_history=True,
        window_requirements={"history_periods": 1},
        category=DerivedMetricCategory.GROWTH,
        description="Quarter-over-quarter revenue growth.",
        is_experimental=False,
        formula=_revenue_growth_qoq,
    ),
    DerivedMetric.REVENUE_GROWTH_TTM: DerivedMetricSpec(
        metric=DerivedMetric.REVENUE_GROWTH_TTM,
        required_statement_types=frozenset({StatementType.INCOME_STATEMENT}),
        required_inputs=frozenset({CanonicalStatementMetric.REVENUE}),
        uses_history=True,
        # 7 prior periods + current payload = 8 periods total.
        window_requirements={"history_periods": 7},
        category=DerivedMetricCategory.GROWTH,
        description=(
            "Trailing-twelve-month revenue growth based on two consecutive " "four-period windows."
        ),
        is_experimental=False,
        formula=_revenue_growth_ttm,
    ),
    DerivedMetric.EPS_DILUTED_GROWTH: DerivedMetricSpec(
        metric=DerivedMetric.EPS_DILUTED_GROWTH,
        required_statement_types=frozenset({StatementType.INCOME_STATEMENT}),
        required_inputs=frozenset({CanonicalStatementMetric.DILUTED_EPS}),
        uses_history=True,
        window_requirements={"history_periods": 1},
        category=DerivedMetricCategory.GROWTH,
        description="Year-over-year growth in diluted EPS.",
        is_experimental=False,
        formula=_eps_diluted_growth,
    ),
    DerivedMetric.EBITDA: DerivedMetricSpec(
        metric=DerivedMetric.EBITDA,
        required_statement_types=frozenset({StatementType.INCOME_STATEMENT}),
        required_inputs=frozenset(
            {
                CanonicalStatementMetric.OPERATING_INCOME,
                CanonicalStatementMetric.DEPRECIATION_AND_AMORTIZATION_EXPENSE,
            },
        ),
        uses_history=False,
        window_requirements={},
        category=DerivedMetricCategory.CASH_FLOW,
        description="Earnings before interest, taxes, depreciation, and amortization.",
        is_experimental=False,
        formula=_ebitda,
    ),
    DerivedMetric.EBIT: DerivedMetricSpec(
        metric=DerivedMetric.EBIT,
        required_statement_types=frozenset({StatementType.INCOME_STATEMENT}),
        required_inputs=frozenset(
            {
                CanonicalStatementMetric.INCOME_BEFORE_TAX,
                CanonicalStatementMetric.INTEREST_EXPENSE,
                CanonicalStatementMetric.INTEREST_INCOME,
            },
        ),
        uses_history=False,
        window_requirements={},
        category=DerivedMetricCategory.CASH_FLOW,
        description="Earnings before interest and taxes.",
        is_experimental=False,
        formula=_ebit,
    ),
    DerivedMetric.LEVERED_FREE_CASH_FLOW: DerivedMetricSpec(
        metric=DerivedMetric.LEVERED_FREE_CASH_FLOW,
        required_statement_types=frozenset({StatementType.CASH_FLOW_STATEMENT}),
        required_inputs=frozenset(
            {
                CanonicalStatementMetric.NET_CASH_FROM_OPERATING_ACTIVITIES,
                CanonicalStatementMetric.CAPITAL_EXPENDITURES,
            },
        ),
        uses_history=False,
        window_requirements={},
        category=DerivedMetricCategory.CASH_FLOW,
        description=(
            "Levered free cash flow; prefers provider FREE_CASH_FLOW when "
            "available, otherwise approximates as CFO + CAPEX."
        ),
        is_experimental=False,
        formula=_levered_free_cash_flow,
    ),
    DerivedMetric.UNLEVERED_FREE_CASH_FLOW: DerivedMetricSpec(
        metric=DerivedMetric.UNLEVERED_FREE_CASH_FLOW,
        required_statement_types=frozenset({StatementType.INCOME_STATEMENT}),
        # IMPORTANT: keep this aligned with legacy behavior. Interest metrics
        # are *not* pre-validated here so that failures surface as "EBIT".
        required_inputs=frozenset(
            {
                CanonicalStatementMetric.INCOME_BEFORE_TAX,
                CanonicalStatementMetric.INCOME_TAX_EXPENSE,
                CanonicalStatementMetric.DEPRECIATION_AND_AMORTIZATION_EXPENSE,
                CanonicalStatementMetric.CAPITAL_EXPENDITURES,
            },
        ),
        uses_history=False,
        window_requirements={},
        category=DerivedMetricCategory.CASH_FLOW,
        description=(
            "Approximate unlevered free cash flow based on NOPAT, "
            "depreciation and amortization, and capital expenditures."
        ),
        is_experimental=True,
        formula=_unlevered_free_cash_flow,
    ),
    DerivedMetric.WORKING_CAPITAL: DerivedMetricSpec(
        metric=DerivedMetric.WORKING_CAPITAL,
        required_statement_types=frozenset({StatementType.BALANCE_SHEET}),
        required_inputs=frozenset(
            {
                CanonicalStatementMetric.TOTAL_CURRENT_ASSETS,
                CanonicalStatementMetric.TOTAL_CURRENT_LIABILITIES,
            },
        ),
        uses_history=False,
        window_requirements={},
        category=DerivedMetricCategory.LEVERAGE,
        description="Current assets minus current liabilities.",
        is_experimental=False,
        formula=_working_capital,
    ),
    DerivedMetric.DEBT_TO_EQUITY: DerivedMetricSpec(
        metric=DerivedMetric.DEBT_TO_EQUITY,
        required_statement_types=frozenset({StatementType.BALANCE_SHEET}),
        required_inputs=frozenset(
            {
                CanonicalStatementMetric.SHORT_TERM_DEBT,
                CanonicalStatementMetric.CURRENT_PORTION_OF_LONG_TERM_DEBT,
                CanonicalStatementMetric.LONG_TERM_DEBT,
                CanonicalStatementMetric.CASH_AND_CASH_EQUIVALENTS,
                CanonicalStatementMetric.TOTAL_EQUITY,
            },
        ),
        uses_history=False,
        window_requirements={},
        category=DerivedMetricCategory.LEVERAGE,
        description="Net debt divided by total equity.",
        is_experimental=False,
        formula=_debt_to_equity,
    ),
    DerivedMetric.INTEREST_COVERAGE: DerivedMetricSpec(
        metric=DerivedMetric.INTEREST_COVERAGE,
        required_statement_types=frozenset({StatementType.INCOME_STATEMENT}),
        required_inputs=frozenset(
            {
                CanonicalStatementMetric.INCOME_BEFORE_TAX,
                CanonicalStatementMetric.INTEREST_EXPENSE,
                CanonicalStatementMetric.INTEREST_INCOME,
            },
        ),
        uses_history=False,
        window_requirements={},
        category=DerivedMetricCategory.LEVERAGE,
        description="EBIT divided by interest expense.",
        is_experimental=False,
        formula=_interest_coverage,
    ),
    DerivedMetric.ROE: DerivedMetricSpec(
        metric=DerivedMetric.ROE,
        required_statement_types=frozenset(
            {StatementType.BALANCE_SHEET, StatementType.INCOME_STATEMENT}
        ),
        required_inputs=frozenset(
            {
                CanonicalStatementMetric.NET_INCOME,
                CanonicalStatementMetric.TOTAL_EQUITY,
            },
        ),
        uses_history=False,
        window_requirements={},
        category=DerivedMetricCategory.RETURN,
        description="Return on equity: net income divided by total equity.",
        is_experimental=False,
        formula=_roe,
    ),
    DerivedMetric.ROA: DerivedMetricSpec(
        metric=DerivedMetric.ROA,
        required_statement_types=frozenset(
            {StatementType.BALANCE_SHEET, StatementType.INCOME_STATEMENT}
        ),
        required_inputs=frozenset(
            {
                CanonicalStatementMetric.NET_INCOME,
                CanonicalStatementMetric.TOTAL_ASSETS,
            },
        ),
        uses_history=False,
        window_requirements={},
        category=DerivedMetricCategory.RETURN,
        description="Return on assets: net income divided by total assets.",
        is_experimental=False,
        formula=_roa,
    ),
    DerivedMetric.ROIC: DerivedMetricSpec(
        metric=DerivedMetric.ROIC,
        required_statement_types=frozenset(
            {StatementType.BALANCE_SHEET, StatementType.INCOME_STATEMENT}
        ),
        required_inputs=frozenset(
            {
                CanonicalStatementMetric.INCOME_BEFORE_TAX,
                CanonicalStatementMetric.INCOME_TAX_EXPENSE,
                CanonicalStatementMetric.TOTAL_EQUITY,
                CanonicalStatementMetric.LONG_TERM_DEBT,
                CanonicalStatementMetric.SHORT_TERM_DEBT,
                CanonicalStatementMetric.CURRENT_PORTION_OF_LONG_TERM_DEBT,
                CanonicalStatementMetric.CASH_AND_CASH_EQUIVALENTS,
                CanonicalStatementMetric.INTEREST_INCOME,
                CanonicalStatementMetric.INTEREST_EXPENSE,
            },
        ),
        uses_history=False,
        window_requirements={},
        category=DerivedMetricCategory.RETURN,
        description=(
            "Return on invested capital: NOPAT divided by invested capital "
            "equity plus interest-bearing debt minus cash."
        ),
        is_experimental=False,
        formula=_roic,
    ),
}

# Backwards-compatible alias; existing code may still reference REGISTRY.
DERIVED_METRIC_REGISTRY: dict[DerivedMetric, DerivedMetricSpec] = DERIVED_METRIC_SPECS


class DerivedMetricsEngine:
    """Compute derived metrics for a canonical statement payload."""

    def compute(
        self,
        *,
        payload: CanonicalStatementPayload,
        history: Sequence[CanonicalStatementPayload],
        metrics: Iterable[DerivedMetric] | None = None,
    ) -> DerivedMetricsResult:
        """Compute derived metrics for a payload.

        Args:
            payload:
                Canonical statement payload representing the current period.
            history:
                Ordered sequence of *prior* canonical payloads for the same
                company (oldest to newest). History may be empty.
            metrics:
                Optional subset of metrics to compute. When None, all metrics
                in :data:`DERIVED_METRIC_SPECS` are attempted.

        Returns:
            DerivedMetricsResult containing successful values and failures.
        """
        requested: list[DerivedMetric] = (
            list(metrics) if metrics is not None else list(DERIVED_METRIC_SPECS.keys())
        )

        ctx = MetricContext(payload=payload, history=history)
        values: dict[DerivedMetric, Decimal] = {}
        failures: list[MetricFailure] = []

        for metric in requested:
            spec = DERIVED_METRIC_SPECS.get(metric)
            value, failure = self._compute_metric(metric=metric, spec=spec, ctx=ctx)
            if failure is not None:
                failures.append(failure)
            elif value is not None:
                values[metric] = value

        return DerivedMetricsResult(values=values, failures=tuple(failures))

    def _compute_metric(
        self,
        *,
        metric: DerivedMetric,
        spec: DerivedMetricSpec | None,
        ctx: MetricContext,
    ) -> tuple[Decimal | None, MetricFailure | None]:
        """Compute a single metric, returning either a value or a failure."""
        if spec is None:
            return None, MetricFailure(
                metric=metric,
                reason=MetricFailureReason.OTHER,
                details={"message": "Metric not registered in DERIVED_METRIC_SPECS."},
            )

        payload = ctx.payload
        history = ctx.history

        # Statement-type applicability check.
        if payload.statement_type not in spec.required_statement_types:
            # Tests expect MISSING_INPUT here, not NOT_APPLICABLE.
            return None, MetricFailure(
                metric=metric,
                reason=MetricFailureReason.MISSING_INPUT,
                details={
                    "message": "Unsupported statement_type for metric.",
                    "statement_type": payload.statement_type.value,
                },
            )

        # Spec-driven input pre-check: ensure all required inputs exist on the payload.
        missing_inputs = [m for m in spec.required_inputs if _get_core_metric(payload, m) is None]
        if missing_inputs:
            return None, MetricFailure(
                metric=metric,
                reason=MetricFailureReason.MISSING_INPUT,
                details={
                    "missing_inputs": ",".join(m.value for m in missing_inputs),
                    # Preserve legacy tests that expect details["message"] == metric name.
                    "message": metric.value,
                },
            )

        # Spec-driven history pre-check for metrics that depend on prior periods.
        history_required = spec.window_requirements.get("history_periods", 0)
        if history_required > 0 and len(history) < history_required:
            # Legacy tests expect this to surface as MISSING_INPUT for growth metrics.
            return None, MetricFailure(
                metric=metric,
                reason=MetricFailureReason.MISSING_INPUT,
                details={
                    "message": metric.value,
                    "required_history_periods": str(history_required),
                    "available_history_periods": str(len(history)),
                },
            )

        try:
            value = spec.formula(ctx)
            return value, None
        except (MissingInputError, InsufficientHistoryError) as exc:
            # Tests treat both as MISSING_INPUT.
            return None, MetricFailure(
                metric=metric,
                reason=MetricFailureReason.MISSING_INPUT,
                details={"message": str(exc)},
            )
        except ZeroDenominatorError as exc:
            return None, MetricFailure(
                metric=metric,
                reason=MetricFailureReason.ZERO_DENOMINATOR,
                details={"message": str(exc)},
            )
        except NegativeDenominatorGuardError as exc:
            return None, MetricFailure(
                metric=metric,
                reason=MetricFailureReason.NEGATIVE_DENOMINATOR_GUARD,
                details={"message": str(exc)},
            )
        except InvalidOperation:
            return None, MetricFailure(
                metric=metric,
                reason=MetricFailureReason.INVALID_OPERATION,
                details={"message": "Invalid decimal operation."},
            )
        except Exception as exc:  # pragma: no cover - defensive
            return None, MetricFailure(
                metric=metric,
                reason=MetricFailureReason.OTHER,
                details={"message": type(exc).__name__},
            )


__all__ = [
    "MetricFailureReason",
    "MetricFailure",
    "MetricContext",
    "DerivedMetricSpec",
    "DerivedMetricsResult",
    "DERIVED_METRIC_SPECS",
    "DERIVED_METRIC_REGISTRY",
    "DerivedMetricsEngine",
]
