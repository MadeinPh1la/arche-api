# tests/unit/domain/entities/test_restatement_delta.py
# Copyright (c)
# SPDX-License-Identifier: MIT
"""Domain tests for RestatementDelta entity.

Scope:
    - RestatementMetricDelta.from_values and has_change semantics.
    - RestatementSummary.from_deltas materiality behavior.
    - RestatementDelta.from_payloads:
        * Union-of-metrics vs explicit filter.
        * Missing metrics treated as zero.
        * No-change metrics excluded from deltas but counted in summary.
"""

from __future__ import annotations

from datetime import date
from decimal import Decimal

from arche_api.domain.entities.canonical_statement_payload import (
    CanonicalStatementPayload,
)
from arche_api.domain.entities.restatement_delta import (
    RestatementDelta,
    RestatementMetricDelta,
    RestatementSummary,
)
from arche_api.domain.enums.canonical_statement_metric import CanonicalStatementMetric
from arche_api.domain.enums.edgar import AccountingStandard, FiscalPeriod, StatementType


def _make_payload(
    *,
    cik: str = "0000320193",
    statement_type: StatementType = StatementType.INCOME_STATEMENT,
    accounting_standard: AccountingStandard = AccountingStandard.US_GAAP,
    statement_date: date = date(2024, 12, 31),
    fiscal_year: int = 2024,
    fiscal_period: FiscalPeriod = FiscalPeriod.FY,
    currency: str = "USD",
    unit_multiplier: int = 1,
    core_metrics: dict[CanonicalStatementMetric, Decimal] | None = None,
    source_accession_id: str = "0000320193-24-000012",
    source_taxonomy: str = "us-gaap-2024",
    source_version_sequence: int = 1,
) -> CanonicalStatementPayload:
    """Helper to build a minimal canonical payload."""
    return CanonicalStatementPayload(
        cik=cik,
        statement_type=statement_type,
        accounting_standard=accounting_standard,
        statement_date=statement_date,
        fiscal_year=fiscal_year,
        fiscal_period=fiscal_period,
        currency=currency,
        unit_multiplier=unit_multiplier,
        core_metrics=core_metrics or {},
        extra_metrics={},
        dimensions={},
        source_accession_id=source_accession_id,
        source_taxonomy=source_taxonomy,
        source_version_sequence=source_version_sequence,
    )


def test_restatement_metric_delta_has_change_true_and_false() -> None:
    """RestatementMetricDelta.has_change reflects underlying diff."""
    changed = RestatementMetricDelta.from_values(
        metric=CanonicalStatementMetric.REVENUE,
        old_value=Decimal("100"),
        new_value=Decimal("120"),
    )
    assert changed.metric is CanonicalStatementMetric.REVENUE
    assert changed.old_value == Decimal("100")
    assert changed.new_value == Decimal("120")
    assert changed.diff == Decimal("20")
    assert changed.has_change is True

    unchanged = RestatementMetricDelta.from_values(
        metric=CanonicalStatementMetric.NET_INCOME,
        old_value=Decimal("10"),
        new_value=Decimal("10"),
    )
    assert unchanged.diff == Decimal("0")
    assert unchanged.has_change is False


def test_restatement_summary_material_and_non_material() -> None:
    """RestatementSummary.from_deltas sets material flag based on changed metrics."""
    unchanged = RestatementMetricDelta.from_values(
        metric=CanonicalStatementMetric.REVENUE,
        old_value=Decimal("100"),
        new_value=Decimal("100"),
    )
    changed = RestatementMetricDelta.from_values(
        metric=CanonicalStatementMetric.NET_INCOME,
        old_value=Decimal("10"),
        new_value=Decimal("12"),
    )

    # Mixed set: one changed, one unchanged.
    summary = RestatementSummary.from_deltas(
        total_compared=2,
        deltas={
            CanonicalStatementMetric.REVENUE: unchanged,
            CanonicalStatementMetric.NET_INCOME: changed,
        },
    )
    assert summary.total_metrics_compared == 2
    assert summary.total_metrics_changed == 1
    assert summary.has_material_change is True

    # No changed metrics → not material.
    summary_none = RestatementSummary.from_deltas(
        total_compared=1,
        deltas={CanonicalStatementMetric.REVENUE: unchanged},
    )
    assert summary_none.total_metrics_compared == 1
    assert summary_none.total_metrics_changed == 0
    assert summary_none.has_material_change is False


def test_restatement_delta_from_payloads_union_and_missing_metrics_as_zero() -> None:
    """from_payloads uses union-of-metrics and treats missing metrics as zero."""
    original = _make_payload(
        core_metrics={
            CanonicalStatementMetric.REVENUE: Decimal("100"),
        },
        source_version_sequence=1,
    )
    restated = _make_payload(
        core_metrics={
            CanonicalStatementMetric.REVENUE: Decimal("120"),  # changed
            CanonicalStatementMetric.NET_INCOME: Decimal("10"),  # new metric
        },
        source_version_sequence=2,
    )

    delta = RestatementDelta.from_payloads(
        cik=original.cik,
        statement_type=original.statement_type,
        fiscal_year=original.fiscal_year,
        fiscal_period=original.fiscal_period,
        original=original,
        restated=restated,
        statement_date=original.statement_date,
        from_version_sequence=1,
        to_version_sequence=2,
        metrics=None,  # use union of metrics
    )

    # Identity is propagated.
    assert delta.identity.cik == original.cik
    assert delta.identity.statement_type is original.statement_type
    assert delta.identity.fiscal_year == original.fiscal_year
    assert delta.identity.fiscal_period is original.fiscal_period
    assert delta.identity.statement_date == original.statement_date
    assert delta.identity.from_version_sequence == 1
    assert delta.identity.to_version_sequence == 2

    # Union-of-metrics: REVENUE + NET_INCOME compared.
    assert delta.summary.total_metrics_compared == 2

    # Both metrics changed (REVENUE 100→120, NET_INCOME 0→10).
    assert delta.summary.total_metrics_changed == 2
    assert delta.summary.has_material_change is True

    deltas = delta.deltas
    assert set(deltas.keys()) == {
        CanonicalStatementMetric.REVENUE,
        CanonicalStatementMetric.NET_INCOME,
    }

    rev_delta = deltas[CanonicalStatementMetric.REVENUE]
    assert rev_delta.old_value == Decimal("100")
    assert rev_delta.new_value == Decimal("120")
    assert rev_delta.diff == Decimal("20")

    ni_delta = deltas[CanonicalStatementMetric.NET_INCOME]
    assert ni_delta.old_value == Decimal("0")  # missing in original → zero
    assert ni_delta.new_value == Decimal("10")
    assert ni_delta.diff == Decimal("10")


def test_restatement_delta_from_payloads_respects_explicit_metric_filter() -> None:
    """from_payloads restricts computation to explicitly supplied metrics."""
    original = _make_payload(
        core_metrics={
            CanonicalStatementMetric.REVENUE: Decimal("100"),
            CanonicalStatementMetric.NET_INCOME: Decimal("10"),
        },
        source_version_sequence=1,
    )
    restated = _make_payload(
        core_metrics={
            CanonicalStatementMetric.REVENUE: Decimal("150"),  # changed
            CanonicalStatementMetric.NET_INCOME: Decimal("15"),  # changed
        },
        source_version_sequence=2,
    )

    # Filter to NET_INCOME only.
    delta = RestatementDelta.from_payloads(
        cik=original.cik,
        statement_type=original.statement_type,
        fiscal_year=original.fiscal_year,
        fiscal_period=original.fiscal_period,
        original=original,
        restated=restated,
        metrics=[CanonicalStatementMetric.NET_INCOME],
    )

    assert delta.summary.total_metrics_compared == 1
    assert delta.summary.total_metrics_changed == 1
    assert CanonicalStatementMetric.REVENUE not in delta.deltas
    assert set(delta.deltas.keys()) == {CanonicalStatementMetric.NET_INCOME}

    ni_delta = delta.deltas[CanonicalStatementMetric.NET_INCOME]
    assert ni_delta.old_value == Decimal("10")
    assert ni_delta.new_value == Decimal("15")
    assert ni_delta.diff == Decimal("5")


def test_restatement_delta_from_payloads_no_payloads_with_metric_filter() -> None:
    """from_payloads handles None payloads by treating all metrics as zero."""
    delta = RestatementDelta.from_payloads(
        cik="0000320193",
        statement_type=StatementType.INCOME_STATEMENT,
        fiscal_year=2024,
        fiscal_period=FiscalPeriod.FY,
        original=None,
        restated=None,
        metrics=[CanonicalStatementMetric.REVENUE],
    )

    # We explicitly asked to compare REVENUE, but there is no change (0→0).
    assert delta.summary.total_metrics_compared == 1
    assert delta.summary.total_metrics_changed == 0
    assert delta.summary.has_material_change is False
    assert delta.deltas == {}
