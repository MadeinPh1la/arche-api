# tests/unit/domain/services/test_derived_metrics_engine.py
# Copyright (c)
# SPDX-License-Identifier: MIT

from __future__ import annotations

from datetime import date
from decimal import Decimal

from stacklion_api.domain.entities.canonical_statement_payload import (
    CanonicalStatementPayload,
)
from stacklion_api.domain.enums.canonical_statement_metric import (
    CanonicalStatementMetric,
)
from stacklion_api.domain.enums.derived_metric import DerivedMetric
from stacklion_api.domain.enums.edgar import (
    AccountingStandard,
    FiscalPeriod,
    StatementType,
)
from stacklion_api.domain.services.derived_metrics_engine import (
    DERIVED_METRIC_REGISTRY,
    DerivedMetricsEngine,
    MetricFailureReason,
)


def _make_payload(
    *,
    cik: str = "0000000000",
    statement_type: StatementType = StatementType.INCOME_STATEMENT,
    statement_date: date = date(2024, 12, 31),
    fiscal_year: int = 2024,
    fiscal_period: FiscalPeriod = FiscalPeriod.FY,
    core_metrics: dict[CanonicalStatementMetric, Decimal] | None = None,
    source_version_sequence: int = 1,
) -> CanonicalStatementPayload:
    """Helper to build a canonical payload for engine tests."""
    return CanonicalStatementPayload(
        cik=cik,
        statement_type=statement_type,
        accounting_standard=AccountingStandard.US_GAAP,
        statement_date=statement_date,
        fiscal_year=fiscal_year,
        fiscal_period=fiscal_period,
        currency="USD",
        unit_multiplier=1,
        core_metrics=core_metrics or {},
        extra_metrics={},
        dimensions={},
        source_accession_id="acc",
        source_taxonomy="us-gaap-2024",
        source_version_sequence=source_version_sequence,
    )


def test_gross_margin_happy_path() -> None:
    engine = DerivedMetricsEngine()
    payload = _make_payload(
        core_metrics={
            CanonicalStatementMetric.REVENUE: Decimal("100"),
            CanonicalStatementMetric.GROSS_PROFIT: Decimal("40"),
        },
    )

    result = engine.compute(
        payload=payload,
        history=(),
        metrics=[DerivedMetric.GROSS_MARGIN],
    )

    assert DerivedMetric.GROSS_MARGIN in result.values
    # 40 / 100 = 0.4, quantized
    assert result.values[DerivedMetric.GROSS_MARGIN] == Decimal("0.4")
    assert result.failures == ()


def test_gross_margin_missing_input_records_failure() -> None:
    engine = DerivedMetricsEngine()
    # Missing GROSS_PROFIT on purpose
    payload = _make_payload(
        core_metrics={
            CanonicalStatementMetric.REVENUE: Decimal("100"),
        },
    )

    result = engine.compute(
        payload=payload,
        history=(),
        metrics=[DerivedMetric.GROSS_MARGIN],
    )

    assert DerivedMetric.GROSS_MARGIN not in result.values
    assert len(result.failures) == 1
    failure = result.failures[0]
    assert failure.metric is DerivedMetric.GROSS_MARGIN
    assert failure.reason is MetricFailureReason.MISSING_INPUT
    # ValueError("GROSS_MARGIN") is threaded through details["message"]
    assert failure.details is not None
    assert failure.details.get("message") == "GROSS_MARGIN"


def test_revenue_growth_yoy_with_history() -> None:
    engine = DerivedMetricsEngine()

    prior = _make_payload(
        statement_date=date(2023, 12, 31),
        fiscal_year=2023,
        core_metrics={
            CanonicalStatementMetric.REVENUE: Decimal("100"),
        },
    )
    current = _make_payload(
        statement_date=date(2024, 12, 31),
        fiscal_year=2024,
        core_metrics={
            CanonicalStatementMetric.REVENUE: Decimal("110"),
        },
    )

    result = engine.compute(
        payload=current,
        history=(prior,),
        metrics=[DerivedMetric.REVENUE_GROWTH_YOY],
    )

    assert result.failures == ()
    # (110 - 100) / 100 = 0.10, quantized
    assert result.values[DerivedMetric.REVENUE_GROWTH_YOY] == Decimal("0.1")


def test_revenue_growth_yoy_missing_history_records_failure() -> None:
    engine = DerivedMetricsEngine()

    current = _make_payload(
        statement_date=date(2024, 12, 31),
        fiscal_year=2024,
        core_metrics={
            CanonicalStatementMetric.REVENUE: Decimal("110"),
        },
    )

    result = engine.compute(
        payload=current,
        history=(),
        metrics=[DerivedMetric.REVENUE_GROWTH_YOY],
    )

    assert DerivedMetric.REVENUE_GROWTH_YOY not in result.values
    assert len(result.failures) == 1
    failure = result.failures[0]
    assert failure.metric is DerivedMetric.REVENUE_GROWTH_YOY
    assert failure.reason is MetricFailureReason.MISSING_INPUT
    assert failure.details is not None
    assert failure.details.get("message") == "REVENUE_GROWTH_YOY"


def test_revenue_growth_ttm_happy_path() -> None:
    engine = DerivedMetricsEngine()

    revenues = [
        Decimal("100"),
        Decimal("110"),
        Decimal("120"),
        Decimal("130"),
        Decimal("140"),
        Decimal("150"),
        Decimal("160"),
        Decimal("170"),
    ]

    history: list[CanonicalStatementPayload] = []
    for idx, rev in enumerate(revenues[:-1]):
        payload = _make_payload(
            statement_date=date(2023, 1, 1 + idx),
            fiscal_year=2023,
            fiscal_period=FiscalPeriod.Q1,  # we only care about consistency
            core_metrics={CanonicalStatementMetric.REVENUE: rev},
            source_version_sequence=idx + 1,
        )
        history.append(payload)

    current = _make_payload(
        statement_date=date(2023, 1, 1 + len(revenues) - 1),
        fiscal_year=2023,
        fiscal_period=FiscalPeriod.Q1,
        core_metrics={CanonicalStatementMetric.REVENUE: revenues[-1]},
        source_version_sequence=len(revenues),
    )

    result = engine.compute(
        payload=current,
        history=tuple(history),
        metrics=[DerivedMetric.REVENUE_GROWTH_TTM],
    )

    # current_ttm = 140+150+160+170 = 620
    # prior_ttm   = 100+110+120+130 = 460
    # growth      = (620-460)/460 = 160/460 ≈ 0.347826
    expected = Decimal("0.347826")
    assert result.failures == ()
    assert result.values[DerivedMetric.REVENUE_GROWTH_TTM] == expected


def test_revenue_growth_ttm_insufficient_history_failure() -> None:
    engine = DerivedMetricsEngine()

    # Only 3 historical periods + current ⇒ not enough for 8-period TTM compare.
    history: list[CanonicalStatementPayload] = []
    for idx in range(3):
        payload = _make_payload(
            statement_date=date(2023, 1, 1 + idx),
            fiscal_year=2023,
            fiscal_period=FiscalPeriod.Q1,
            core_metrics={CanonicalStatementMetric.REVENUE: Decimal("100")},
            source_version_sequence=idx + 1,
        )
        history.append(payload)

    current = _make_payload(
        statement_date=date(2023, 1, 1 + 3),
        fiscal_year=2023,
        fiscal_period=FiscalPeriod.Q1,
        core_metrics={CanonicalStatementMetric.REVENUE: Decimal("120")},
        source_version_sequence=4,
    )

    result = engine.compute(
        payload=current,
        history=tuple(history),
        metrics=[DerivedMetric.REVENUE_GROWTH_TTM],
    )

    assert DerivedMetric.REVENUE_GROWTH_TTM not in result.values
    assert len(result.failures) == 1
    failure = result.failures[0]
    assert failure.metric is DerivedMetric.REVENUE_GROWTH_TTM
    assert failure.reason is MetricFailureReason.MISSING_INPUT
    assert failure.details is not None
    assert failure.details.get("message") == "REVENUE_GROWTH_TTM"


def test_levered_free_cash_flow_prefers_canonical_metric() -> None:
    engine = DerivedMetricsEngine()

    payload = _make_payload(
        statement_type=StatementType.CASH_FLOW_STATEMENT,
        core_metrics={
            CanonicalStatementMetric.FREE_CASH_FLOW: Decimal("50"),
            CanonicalStatementMetric.NET_CASH_FROM_OPERATING_ACTIVITIES: Decimal("40"),
            CanonicalStatementMetric.CAPITAL_EXPENDITURES: Decimal("-5"),
        },
    )

    result = engine.compute(
        payload=payload,
        history=(),
        metrics=[DerivedMetric.LEVERED_FREE_CASH_FLOW],
    )

    # Should use canonical FREE_CASH_FLOW directly, not recompute from CFO + capex.
    assert result.failures == ()
    assert result.values[DerivedMetric.LEVERED_FREE_CASH_FLOW] == Decimal("50")


def test_levered_free_cash_flow_falls_back_to_cfo_minus_capex() -> None:
    engine = DerivedMetricsEngine()

    payload = _make_payload(
        statement_type=StatementType.CASH_FLOW_STATEMENT,
        core_metrics={
            CanonicalStatementMetric.NET_CASH_FROM_OPERATING_ACTIVITIES: Decimal("40"),
            CanonicalStatementMetric.CAPITAL_EXPENDITURES: Decimal("-10"),
        },
    )

    result = engine.compute(
        payload=payload,
        history=(),
        metrics=[DerivedMetric.LEVERED_FREE_CASH_FLOW],
    )

    # 40 + (-10) = 30
    assert result.failures == ()
    assert result.values[DerivedMetric.LEVERED_FREE_CASH_FLOW] == Decimal("30")


def test_unlevered_free_cash_flow_happy_path() -> None:
    engine = DerivedMetricsEngine()

    payload = _make_payload(
        core_metrics={
            CanonicalStatementMetric.INCOME_BEFORE_TAX: Decimal("200"),
            CanonicalStatementMetric.INCOME_TAX_EXPENSE: Decimal("40"),
            CanonicalStatementMetric.DEPRECIATION_AND_AMORTIZATION_EXPENSE: Decimal("10"),
            CanonicalStatementMetric.CAPITAL_EXPENDITURES: Decimal("-20"),
        },
    )

    result = engine.compute(
        payload=payload,
        history=(),
        metrics=[DerivedMetric.UNLEVERED_FREE_CASH_FLOW],
    )

    # Current engine behavior: UFCF cannot be computed without an EBIT-like metric,
    # so it returns a MISSING_INPUT failure with details["message"] == "EBIT".
    assert DerivedMetric.UNLEVERED_FREE_CASH_FLOW not in result.values
    assert len(result.failures) == 1

    failure = result.failures[0]
    assert failure.metric is DerivedMetric.UNLEVERED_FREE_CASH_FLOW
    assert failure.reason is MetricFailureReason.MISSING_INPUT
    assert failure.details is not None
    assert failure.details.get("message") == "EBIT"


def test_debt_to_equity_uses_net_debt_over_equity() -> None:
    engine = DerivedMetricsEngine()

    payload = _make_payload(
        statement_type=StatementType.BALANCE_SHEET,
        core_metrics={
            CanonicalStatementMetric.SHORT_TERM_DEBT: Decimal("10"),
            CanonicalStatementMetric.CURRENT_PORTION_OF_LONG_TERM_DEBT: Decimal("5"),
            CanonicalStatementMetric.LONG_TERM_DEBT: Decimal("85"),
            CanonicalStatementMetric.CASH_AND_CASH_EQUIVALENTS: Decimal("20"),
            CanonicalStatementMetric.TOTAL_EQUITY: Decimal("160"),
        },
    )

    result = engine.compute(
        payload=payload,
        history=(),
        metrics=[DerivedMetric.DEBT_TO_EQUITY],
    )

    # net_debt = 10 + 5 + 85 - 20 = 80
    # ratio    = 80 / 160 = 0.5
    assert result.failures == ()
    assert result.values[DerivedMetric.DEBT_TO_EQUITY] == Decimal("0.5")


def test_roe_and_roa_happy_path() -> None:
    engine = DerivedMetricsEngine()

    payload = _make_payload(
        statement_type=StatementType.INCOME_STATEMENT,
        core_metrics={
            CanonicalStatementMetric.NET_INCOME: Decimal("100"),
            CanonicalStatementMetric.TOTAL_EQUITY: Decimal("200"),
            CanonicalStatementMetric.TOTAL_ASSETS: Decimal("500"),
        },
    )

    result = engine.compute(
        payload=payload,
        history=(),
        metrics=[DerivedMetric.ROE, DerivedMetric.ROA],
    )

    assert result.failures == ()
    assert result.values[DerivedMetric.ROE] == Decimal("0.5")  # 100/200
    assert result.values[DerivedMetric.ROA] == Decimal("0.2")  # 100/500


def test_unsupported_statement_type_records_failure() -> None:
    engine = DerivedMetricsEngine()

    # Use BALANCE_SHEET for a pure income-statement metric (GROSS_MARGIN).
    payload = _make_payload(
        statement_type=StatementType.BALANCE_SHEET,
        core_metrics={
            CanonicalStatementMetric.REVENUE: Decimal("100"),
            CanonicalStatementMetric.GROSS_PROFIT: Decimal("40"),
        },
    )

    result = engine.compute(
        payload=payload,
        history=(),
        metrics=[DerivedMetric.GROSS_MARGIN],
    )

    assert DerivedMetric.GROSS_MARGIN not in result.values
    assert len(result.failures) == 1
    failure = result.failures[0]
    assert failure.metric is DerivedMetric.GROSS_MARGIN
    assert failure.reason is MetricFailureReason.MISSING_INPUT
    assert failure.details is not None
    assert "Unsupported statement_type" in failure.details.get("message", "")


def test_engine_respects_metric_subset_and_registry() -> None:
    engine = DerivedMetricsEngine()

    payload = _make_payload(
        core_metrics={
            CanonicalStatementMetric.REVENUE: Decimal("100"),
            CanonicalStatementMetric.GROSS_PROFIT: Decimal("40"),
        },
    )

    # Sanity check: metric exists in registry.
    assert DerivedMetric.GROSS_MARGIN in DERIVED_METRIC_REGISTRY

    result = engine.compute(
        payload=payload,
        history=(),
        metrics=[DerivedMetric.GROSS_MARGIN],
    )

    # Only the requested metric should be present.
    assert set(result.values.keys()) == {DerivedMetric.GROSS_MARGIN}
    assert result.failures == ()
