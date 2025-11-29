# src/stacklion_api/domain/services/derived_metrics_engine.py
# Copyright (c) Stacklion.
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
"""

from __future__ import annotations

from collections.abc import Callable, Iterable, Sequence
from dataclasses import dataclass
from decimal import Decimal, InvalidOperation, getcontext
from enum import Enum

from stacklion_api.domain.entities.canonical_statement_payload import CanonicalStatementPayload
from stacklion_api.domain.enums.canonical_statement_metric import CanonicalStatementMetric
from stacklion_api.domain.enums.derived_metric import DerivedMetric
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
class DerivedMetricDefinition:
    """Definition of a derived metric and its computation formula."""

    metric: DerivedMetric
    required_statement_types: frozenset[StatementType]
    required_base_metrics: frozenset[CanonicalStatementMetric]
    uses_history: bool
    formula: Callable[[MetricContext], Decimal]


@dataclass(frozen=True)
class DerivedMetricsResult:
    """Result of computing one or more derived metrics."""

    values: dict[DerivedMetric, Decimal]
    failures: tuple[MetricFailure, ...]


def _get_core_metric(
    payload: CanonicalStatementPayload,
    metric: CanonicalStatementMetric,
) -> Decimal | None:
    """Return a core metric value from a payload or None if absent."""
    value = payload.core_metrics.get(metric)
    return value


def _quantize_ratio(value: Decimal) -> Decimal:
    """Quantize ratio-like values to a stable number of decimal places."""
    # Convert to 6 decimal places (RATIO_SCALE); avoid raising on tiny numbers.
    try:
        return (value / RATIO_SCALE).to_integral_value() * RATIO_SCALE
    except (InvalidOperation, ZeroDivisionError):
        return value


def _safe_divide(
    numerator: Decimal | None,
    denominator: Decimal | None,
) -> Decimal | None:
    """Safely divide two Decimals, returning None on invalid operations."""
    if numerator is None or denominator is None:
        return None

    if denominator == DECIMAL_ZERO:
        return None

    # Guard against extremely small denominators that would explode ratios.
    if abs(denominator) < DECIMAL_EPSILON:
        return None

    try:
        return numerator / denominator
    except InvalidOperation:
        return None


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
        # Very simple: pick the last payload with same statement_type and a
        # strictly earlier statement_date.
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
    if ratio is None:
        raise ValueError("GROSS_MARGIN")
    return _quantize_ratio(ratio)


def _operating_margin(ctx: MetricContext) -> Decimal:
    revenue = _get_core_metric(ctx.payload, CanonicalStatementMetric.REVENUE)
    operating_income = _get_core_metric(ctx.payload, CanonicalStatementMetric.OPERATING_INCOME)
    ratio = _safe_divide(operating_income, revenue)
    if ratio is None:
        raise ValueError("OPERATING_MARGIN")
    return _quantize_ratio(ratio)


def _net_margin(ctx: MetricContext) -> Decimal:
    revenue = _get_core_metric(ctx.payload, CanonicalStatementMetric.REVENUE)
    net_income = _get_core_metric(ctx.payload, CanonicalStatementMetric.NET_INCOME)
    ratio = _safe_divide(net_income, revenue)
    if ratio is None:
        raise ValueError("NET_MARGIN")
    return _quantize_ratio(ratio)


def _revenue_growth_yoy(ctx: MetricContext) -> Decimal:
    current_rev = _get_core_metric(ctx.payload, CanonicalStatementMetric.REVENUE)
    prior = _select_prior_payload(ctx, years_back=1)
    prior_rev = None if prior is None else _get_core_metric(prior, CanonicalStatementMetric.REVENUE)
    delta_ratio = _safe_divide(
        None if current_rev is None or prior_rev is None else current_rev - prior_rev,
        prior_rev,
    )
    if delta_ratio is None:
        raise ValueError("REVENUE_GROWTH_YOY")
    return _quantize_ratio(delta_ratio)


def _revenue_growth_qoq(ctx: MetricContext) -> Decimal:
    current_rev = _get_core_metric(ctx.payload, CanonicalStatementMetric.REVENUE)
    prior = _select_prior_payload(ctx, quarters_back=1)
    prior_rev = None if prior is None else _get_core_metric(prior, CanonicalStatementMetric.REVENUE)
    delta_ratio = _safe_divide(
        None if current_rev is None or prior_rev is None else current_rev - prior_rev,
        prior_rev,
    )
    if delta_ratio is None:
        raise ValueError("REVENUE_GROWTH_QOQ")
    return _quantize_ratio(delta_ratio)


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
        - Requires at least 8 comparable periods for a valid TTM comparison.
        - Raises ValueError("REVENUE_GROWTH_TTM") when:
            * fewer than 8 comparable periods are available,
            * any period in the TTM or prior-TTM window is missing REVENUE,
            * division by zero or numerically unstable denominators occur.
    """
    relevant: list[CanonicalStatementPayload] = [
        p for p in ctx.history if p.statement_type == ctx.payload.statement_type
    ]
    relevant.append(ctx.payload)
    relevant = sorted(relevant, key=lambda p: p.statement_date)

    last_four = relevant[-4:]
    if len(last_four) < 4:
        raise ValueError("REVENUE_GROWTH_TTM")

    current_ttm = DECIMAL_ZERO
    for p in last_four:
        rev = _get_core_metric(p, CanonicalStatementMetric.REVENUE)
        if rev is None:
            raise ValueError("REVENUE_GROWTH_TTM")
        current_ttm += rev

    if len(relevant) < 8:
        raise ValueError("REVENUE_GROWTH_TTM")

    prior_four = relevant[-8:-4]
    prior_ttm = DECIMAL_ZERO
    for p in prior_four:
        rev = _get_core_metric(p, CanonicalStatementMetric.REVENUE)
        if rev is None:
            raise ValueError("REVENUE_GROWTH_TTM")
        prior_ttm += rev

    delta_ratio = _safe_divide(current_ttm - prior_ttm, prior_ttm)
    if delta_ratio is None:
        raise ValueError("REVENUE_GROWTH_TTM")

    return _quantize_ratio(delta_ratio)


def _eps_diluted_growth(ctx: MetricContext) -> Decimal:
    current_eps = _get_core_metric(ctx.payload, CanonicalStatementMetric.DILUTED_EPS)
    prior = _select_prior_payload(ctx, years_back=1)
    prior_eps = (
        None if prior is None else _get_core_metric(prior, CanonicalStatementMetric.DILUTED_EPS)
    )
    delta_ratio = _safe_divide(
        None if current_eps is None or prior_eps is None else current_eps - prior_eps,
        prior_eps,
    )
    if delta_ratio is None:
        raise ValueError("EPS_DILUTED_GROWTH")
    return _quantize_ratio(delta_ratio)


def _ebitda(ctx: MetricContext) -> Decimal:
    operating_income = _get_core_metric(ctx.payload, CanonicalStatementMetric.OPERATING_INCOME)
    da = _get_core_metric(
        ctx.payload, CanonicalStatementMetric.DEPRECIATION_AND_AMORTIZATION_EXPENSE
    )
    if operating_income is None or da is None:
        raise ValueError("EBITDA")
    return operating_income + da


def _ebit(ctx: MetricContext) -> Decimal:
    income_before_tax = _get_core_metric(ctx.payload, CanonicalStatementMetric.INCOME_BEFORE_TAX)
    interest_expense = _get_core_metric(ctx.payload, CanonicalStatementMetric.INTEREST_EXPENSE)
    interest_income = _get_core_metric(ctx.payload, CanonicalStatementMetric.INTEREST_INCOME)
    if income_before_tax is None or interest_expense is None or interest_income is None:
        raise ValueError("EBIT")
    return income_before_tax + interest_expense - interest_income


def _levered_free_cash_flow(ctx: MetricContext) -> Decimal:
    # Prefer canonical FREE_CASH_FLOW if present.
    fcf = _get_core_metric(ctx.payload, CanonicalStatementMetric.FREE_CASH_FLOW)
    if fcf is not None:
        return fcf

    # Fallback: approximate LFCF from cash flow statement.
    cfo = _get_core_metric(ctx.payload, CanonicalStatementMetric.NET_CASH_FROM_OPERATING_ACTIVITIES)
    capex = _get_core_metric(ctx.payload, CanonicalStatementMetric.CAPITAL_EXPENDITURES)
    if cfo is None or capex is None:
        raise ValueError("LEVERED_FREE_CASH_FLOW")
    return cfo + capex


def _unlevered_free_cash_flow(ctx: MetricContext) -> Decimal:
    ebit = _ebit(ctx)
    income_tax_expense = _get_core_metric(ctx.payload, CanonicalStatementMetric.INCOME_TAX_EXPENSE)
    income_before_tax = _get_core_metric(ctx.payload, CanonicalStatementMetric.INCOME_BEFORE_TAX)
    da = _get_core_metric(
        ctx.payload, CanonicalStatementMetric.DEPRECIATION_AND_AMORTIZATION_EXPENSE
    )
    capex = _get_core_metric(ctx.payload, CanonicalStatementMetric.CAPITAL_EXPENDITURES)

    if income_tax_expense is None or income_before_tax is None or da is None or capex is None:
        raise ValueError("UNLEVERED_FREE_CASH_FLOW")

    tax_rate = _safe_divide(income_tax_expense, income_before_tax)
    if tax_rate is None:
        raise ValueError("UNLEVERED_FREE_CASH_FLOW")

    nopat = ebit * (DECIMAL_ONE - tax_rate)

    # Working-capital delta is computed at the application layer from balance
    # sheet payloads; in the pure per-period engine we approximate ΔWC as 0.
    delta_working_capital = DECIMAL_ZERO

    return nopat + da + capex - delta_working_capital


def _working_capital(ctx: MetricContext) -> Decimal:
    current_assets = _get_core_metric(ctx.payload, CanonicalStatementMetric.TOTAL_CURRENT_ASSETS)
    current_liabilities = _get_core_metric(
        ctx.payload,
        CanonicalStatementMetric.TOTAL_CURRENT_LIABILITIES,
    )
    if current_assets is None or current_liabilities is None:
        raise ValueError("WORKING_CAPITAL")
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
        _get_core_metric(ctx.payload, CanonicalStatementMetric.CASH_AND_CASH_EQUIVALENTS)
        or DECIMAL_ZERO
    )
    total_equity = _get_core_metric(ctx.payload, CanonicalStatementMetric.TOTAL_EQUITY)

    if total_equity is None:
        raise ValueError("DEBT_TO_EQUITY")

    net_debt = short_term_debt + current_portion_ltd + long_term_debt - cash
    ratio = _safe_divide(net_debt, total_equity)
    if ratio is None:
        raise ValueError("DEBT_TO_EQUITY")
    return _quantize_ratio(ratio)


def _interest_coverage(ctx: MetricContext) -> Decimal:
    ebit = _ebit(ctx)
    interest_expense = _get_core_metric(ctx.payload, CanonicalStatementMetric.INTEREST_EXPENSE)
    ratio = _safe_divide(ebit, interest_expense)
    if ratio is None:
        raise ValueError("INTEREST_COVERAGE")
    return _quantize_ratio(ratio)


def _roe(ctx: MetricContext) -> Decimal:
    net_income = _get_core_metric(ctx.payload, CanonicalStatementMetric.NET_INCOME)
    total_equity = _get_core_metric(ctx.payload, CanonicalStatementMetric.TOTAL_EQUITY)

    if net_income is None or total_equity is None:
        raise ValueError("ROE")

    ratio = _safe_divide(net_income, total_equity)
    if ratio is None:
        raise ValueError("ROE")
    return _quantize_ratio(ratio)


def _roa(ctx: MetricContext) -> Decimal:
    net_income = _get_core_metric(ctx.payload, CanonicalStatementMetric.NET_INCOME)
    total_assets = _get_core_metric(ctx.payload, CanonicalStatementMetric.TOTAL_ASSETS)

    if net_income is None or total_assets is None:
        raise ValueError("ROA")

    ratio = _safe_divide(net_income, total_assets)
    if ratio is None:
        raise ValueError("ROA")
    return _quantize_ratio(ratio)


def _roic(ctx: MetricContext) -> Decimal:
    ebit = _ebit(ctx)
    income_tax_expense = _get_core_metric(ctx.payload, CanonicalStatementMetric.INCOME_TAX_EXPENSE)
    income_before_tax = _get_core_metric(ctx.payload, CanonicalStatementMetric.INCOME_BEFORE_TAX)
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
        _get_core_metric(ctx.payload, CanonicalStatementMetric.CASH_AND_CASH_EQUIVALENTS)
        or DECIMAL_ZERO
    )

    if income_tax_expense is None or income_before_tax is None or total_equity is None:
        raise ValueError("ROIC")

    tax_rate = _safe_divide(income_tax_expense, income_before_tax)
    if tax_rate is None:
        raise ValueError("ROIC")

    nopat = ebit * (DECIMAL_ONE - tax_rate)

    invested_capital = total_equity + long_term_debt + short_term_debt + current_portion_ltd - cash
    ratio = _safe_divide(nopat, invested_capital)
    if ratio is None:
        raise ValueError("ROIC")
    return _quantize_ratio(ratio)


# --------------------------------------------------------------------------- #
# Registry and engine                                                         #
# --------------------------------------------------------------------------- #


DERIVED_METRIC_REGISTRY: dict[DerivedMetric, DerivedMetricDefinition] = {
    DerivedMetric.GROSS_MARGIN: DerivedMetricDefinition(
        metric=DerivedMetric.GROSS_MARGIN,
        required_statement_types=frozenset({StatementType.INCOME_STATEMENT}),
        required_base_metrics=frozenset(
            {
                CanonicalStatementMetric.REVENUE,
                CanonicalStatementMetric.GROSS_PROFIT,
            },
        ),
        uses_history=False,
        formula=_gross_margin,
    ),
    DerivedMetric.OPERATING_MARGIN: DerivedMetricDefinition(
        metric=DerivedMetric.OPERATING_MARGIN,
        required_statement_types=frozenset({StatementType.INCOME_STATEMENT}),
        required_base_metrics=frozenset(
            {
                CanonicalStatementMetric.REVENUE,
                CanonicalStatementMetric.OPERATING_INCOME,
            },
        ),
        uses_history=False,
        formula=_operating_margin,
    ),
    DerivedMetric.NET_MARGIN: DerivedMetricDefinition(
        metric=DerivedMetric.NET_MARGIN,
        required_statement_types=frozenset({StatementType.INCOME_STATEMENT}),
        required_base_metrics=frozenset(
            {
                CanonicalStatementMetric.REVENUE,
                CanonicalStatementMetric.NET_INCOME,
            },
        ),
        uses_history=False,
        formula=_net_margin,
    ),
    DerivedMetric.REVENUE_GROWTH_YOY: DerivedMetricDefinition(
        metric=DerivedMetric.REVENUE_GROWTH_YOY,
        required_statement_types=frozenset({StatementType.INCOME_STATEMENT}),
        required_base_metrics=frozenset({CanonicalStatementMetric.REVENUE}),
        uses_history=True,
        formula=_revenue_growth_yoy,
    ),
    DerivedMetric.REVENUE_GROWTH_QOQ: DerivedMetricDefinition(
        metric=DerivedMetric.REVENUE_GROWTH_QOQ,
        required_statement_types=frozenset({StatementType.INCOME_STATEMENT}),
        required_base_metrics=frozenset({CanonicalStatementMetric.REVENUE}),
        uses_history=True,
        formula=_revenue_growth_qoq,
    ),
    DerivedMetric.REVENUE_GROWTH_TTM: DerivedMetricDefinition(
        metric=DerivedMetric.REVENUE_GROWTH_TTM,
        required_statement_types=frozenset({StatementType.INCOME_STATEMENT}),
        required_base_metrics=frozenset({CanonicalStatementMetric.REVENUE}),
        uses_history=True,
        formula=_revenue_growth_ttm,
    ),
    DerivedMetric.EPS_DILUTED_GROWTH: DerivedMetricDefinition(
        metric=DerivedMetric.EPS_DILUTED_GROWTH,
        required_statement_types=frozenset({StatementType.INCOME_STATEMENT}),
        required_base_metrics=frozenset({CanonicalStatementMetric.DILUTED_EPS}),
        uses_history=True,
        formula=_eps_diluted_growth,
    ),
    DerivedMetric.EBITDA: DerivedMetricDefinition(
        metric=DerivedMetric.EBITDA,
        required_statement_types=frozenset({StatementType.INCOME_STATEMENT}),
        required_base_metrics=frozenset(
            {
                CanonicalStatementMetric.OPERATING_INCOME,
                CanonicalStatementMetric.DEPRECIATION_AND_AMORTIZATION_EXPENSE,
            },
        ),
        uses_history=False,
        formula=_ebitda,
    ),
    DerivedMetric.EBIT: DerivedMetricDefinition(
        metric=DerivedMetric.EBIT,
        required_statement_types=frozenset({StatementType.INCOME_STATEMENT}),
        required_base_metrics=frozenset(
            {
                CanonicalStatementMetric.INCOME_BEFORE_TAX,
                CanonicalStatementMetric.INTEREST_EXPENSE,
                CanonicalStatementMetric.INTEREST_INCOME,
            },
        ),
        uses_history=False,
        formula=_ebit,
    ),
    DerivedMetric.LEVERED_FREE_CASH_FLOW: DerivedMetricDefinition(
        metric=DerivedMetric.LEVERED_FREE_CASH_FLOW,
        required_statement_types=frozenset({StatementType.CASH_FLOW_STATEMENT}),
        required_base_metrics=frozenset(
            {
                CanonicalStatementMetric.FREE_CASH_FLOW,
                CanonicalStatementMetric.NET_CASH_FROM_OPERATING_ACTIVITIES,
                CanonicalStatementMetric.CAPITAL_EXPENDITURES,
            },
        ),
        uses_history=False,
        formula=_levered_free_cash_flow,
    ),
    DerivedMetric.UNLEVERED_FREE_CASH_FLOW: DerivedMetricDefinition(
        metric=DerivedMetric.UNLEVERED_FREE_CASH_FLOW,
        required_statement_types=frozenset({StatementType.INCOME_STATEMENT}),
        required_base_metrics=frozenset(
            {
                CanonicalStatementMetric.INCOME_BEFORE_TAX,
                CanonicalStatementMetric.INCOME_TAX_EXPENSE,
                CanonicalStatementMetric.DEPRECIATION_AND_AMORTIZATION_EXPENSE,
                CanonicalStatementMetric.CAPITAL_EXPENDITURES,
            },
        ),
        uses_history=False,
        formula=_unlevered_free_cash_flow,
    ),
    DerivedMetric.WORKING_CAPITAL: DerivedMetricDefinition(
        metric=DerivedMetric.WORKING_CAPITAL,
        required_statement_types=frozenset({StatementType.BALANCE_SHEET}),
        required_base_metrics=frozenset(
            {
                CanonicalStatementMetric.TOTAL_CURRENT_ASSETS,
                CanonicalStatementMetric.TOTAL_CURRENT_LIABILITIES,
            },
        ),
        uses_history=False,
        formula=_working_capital,
    ),
    DerivedMetric.DEBT_TO_EQUITY: DerivedMetricDefinition(
        metric=DerivedMetric.DEBT_TO_EQUITY,
        required_statement_types=frozenset({StatementType.BALANCE_SHEET}),
        required_base_metrics=frozenset(
            {
                CanonicalStatementMetric.SHORT_TERM_DEBT,
                CanonicalStatementMetric.CURRENT_PORTION_OF_LONG_TERM_DEBT,
                CanonicalStatementMetric.LONG_TERM_DEBT,
                CanonicalStatementMetric.CASH_AND_CASH_EQUIVALENTS,
                CanonicalStatementMetric.TOTAL_EQUITY,
            },
        ),
        uses_history=False,
        formula=_debt_to_equity,
    ),
    DerivedMetric.INTEREST_COVERAGE: DerivedMetricDefinition(
        metric=DerivedMetric.INTEREST_COVERAGE,
        required_statement_types=frozenset({StatementType.INCOME_STATEMENT}),
        required_base_metrics=frozenset(
            {
                CanonicalStatementMetric.INCOME_BEFORE_TAX,
                CanonicalStatementMetric.INTEREST_EXPENSE,
                CanonicalStatementMetric.INTEREST_INCOME,
            },
        ),
        uses_history=False,
        formula=_interest_coverage,
    ),
    DerivedMetric.ROE: DerivedMetricDefinition(
        metric=DerivedMetric.ROE,
        required_statement_types=frozenset(
            {StatementType.BALANCE_SHEET, StatementType.INCOME_STATEMENT}
        ),
        required_base_metrics=frozenset(
            {
                CanonicalStatementMetric.NET_INCOME,
                CanonicalStatementMetric.TOTAL_EQUITY,
            },
        ),
        uses_history=False,
        formula=_roe,
    ),
    DerivedMetric.ROA: DerivedMetricDefinition(
        metric=DerivedMetric.ROA,
        required_statement_types=frozenset(
            {StatementType.BALANCE_SHEET, StatementType.INCOME_STATEMENT}
        ),
        required_base_metrics=frozenset(
            {
                CanonicalStatementMetric.NET_INCOME,
                CanonicalStatementMetric.TOTAL_ASSETS,
            },
        ),
        uses_history=False,
        formula=_roa,
    ),
    DerivedMetric.ROIC: DerivedMetricDefinition(
        metric=DerivedMetric.ROIC,
        required_statement_types=frozenset(
            {StatementType.BALANCE_SHEET, StatementType.INCOME_STATEMENT}
        ),
        required_base_metrics=frozenset(
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
        formula=_roic,
    ),
}


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
                in :data:`DERIVED_METRIC_REGISTRY` are attempted.

        Returns:
            DerivedMetricsResult containing successful values and failures.
        """
        requested: list[DerivedMetric] = (
            list(metrics) if metrics is not None else list(DERIVED_METRIC_REGISTRY.keys())
        )

        ctx = MetricContext(payload=payload, history=history)
        values: dict[DerivedMetric, Decimal] = {}
        failures: list[MetricFailure] = []

        for metric in requested:
            definition = DERIVED_METRIC_REGISTRY.get(metric)
            if definition is None:
                failures.append(
                    MetricFailure(
                        metric=metric,
                        reason=MetricFailureReason.OTHER,
                        details={"message": "Metric not registered in DERIVED_METRIC_REGISTRY."},
                    ),
                )
                continue

            if payload.statement_type not in definition.required_statement_types:
                failures.append(
                    MetricFailure(
                        metric=metric,
                        reason=MetricFailureReason.MISSING_INPUT,
                        details={"message": "Unsupported statement_type for metric."},
                    ),
                )
                continue

            # For history-dependent metrics we simply rely on the formula to
            # inspect ctx.history and raise on insufficient data.
            try:
                value = definition.formula(ctx)
            except ValueError as exc:
                failures.append(
                    MetricFailure(
                        metric=metric,
                        reason=MetricFailureReason.MISSING_INPUT,
                        details={"message": str(exc)},
                    ),
                )
                continue
            except InvalidOperation:
                failures.append(
                    MetricFailure(
                        metric=metric,
                        reason=MetricFailureReason.INVALID_OPERATION,
                        details={"message": "Invalid decimal operation."},
                    ),
                )
                continue
            except Exception as exc:  # pragma: no cover - defensive
                failures.append(
                    MetricFailure(
                        metric=metric,
                        reason=MetricFailureReason.OTHER,
                        details={"message": type(exc).__name__},
                    ),
                )
                continue

            values[metric] = value

        return DerivedMetricsResult(values=values, failures=tuple(failures))


__all__ = [
    "MetricFailureReason",
    "MetricFailure",
    "MetricContext",
    "DerivedMetricDefinition",
    "DerivedMetricsResult",
    "DERIVED_METRIC_REGISTRY",
    "DerivedMetricsEngine",
]
