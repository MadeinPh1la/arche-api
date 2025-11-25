# tests/unit/domain/test_edgar_restatement_delta.py
# Copyright (c)
# SPDX-License-Identifier: MIT

from __future__ import annotations

from datetime import date
from decimal import Decimal

import pytest

from stacklion_api.domain.entities.canonical_statement_payload import (
    CanonicalStatementPayload,
)
from stacklion_api.domain.entities.edgar_restatement_delta import (
    RestatementDelta,
    RestatementMetricDelta,
    compute_restatement_delta,
)
from stacklion_api.domain.enums.canonical_statement_metric import CanonicalStatementMetric
from stacklion_api.domain.enums.edgar import AccountingStandard, FiscalPeriod, StatementType
from stacklion_api.domain.exceptions.edgar import EdgarMappingError


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


def test_compute_restatement_delta_happy_path_includes_only_changed_metrics() -> None:
    payload_v1 = _make_payload(
        core_metrics={
            CanonicalStatementMetric.REVENUE: Decimal("100"),
            CanonicalStatementMetric.NET_INCOME: Decimal("10"),
        },
        source_version_sequence=1,
    )
    payload_v2 = _make_payload(
        core_metrics={
            CanonicalStatementMetric.REVENUE: Decimal("120"),  # changed
            CanonicalStatementMetric.NET_INCOME: Decimal("10"),  # unchanged
        },
        source_version_sequence=2,
    )

    result = compute_restatement_delta(from_payload=payload_v1, to_payload=payload_v2)

    assert isinstance(result, RestatementDelta)
    assert result.cik == payload_v1.cik
    assert result.from_version_sequence == 1
    assert result.to_version_sequence == 2

    # Only REVENUE should appear; NET_INCOME is unchanged.
    assert list(result.metrics.keys()) == [CanonicalStatementMetric.REVENUE]
    delta = result.metrics[CanonicalStatementMetric.REVENUE]
    assert isinstance(delta, RestatementMetricDelta)
    assert delta.old == Decimal("100")
    assert delta.new == Decimal("120")
    assert delta.diff == Decimal("20")


def test_compute_restatement_delta_respects_metric_filter() -> None:
    payload_v1 = _make_payload(
        core_metrics={
            CanonicalStatementMetric.REVENUE: Decimal("100"),
            CanonicalStatementMetric.NET_INCOME: Decimal("10"),
        },
        source_version_sequence=1,
    )
    payload_v2 = _make_payload(
        core_metrics={
            CanonicalStatementMetric.REVENUE: Decimal("120"),
            CanonicalStatementMetric.NET_INCOME: Decimal("15"),
        },
        source_version_sequence=2,
    )

    result = compute_restatement_delta(
        from_payload=payload_v1,
        to_payload=payload_v2,
        metrics=[CanonicalStatementMetric.NET_INCOME],
    )

    assert list(result.metrics.keys()) == [CanonicalStatementMetric.NET_INCOME]
    delta = result.metrics[CanonicalStatementMetric.NET_INCOME]
    assert delta.old == Decimal("10")
    assert delta.new == Decimal("15")
    assert delta.diff == Decimal("5")


def test_compute_restatement_delta_ignores_metrics_missing_on_either_side() -> None:
    payload_v1 = _make_payload(
        core_metrics={CanonicalStatementMetric.REVENUE: Decimal("100")},
        source_version_sequence=1,
    )
    # Only NET_INCOME present in v2; REVENUE missing. Intersection is empty.
    payload_v2 = _make_payload(
        core_metrics={CanonicalStatementMetric.NET_INCOME: Decimal("10")},
        source_version_sequence=2,
    )

    result = compute_restatement_delta(from_payload=payload_v1, to_payload=payload_v2)

    assert result.metrics == {}


@pytest.mark.parametrize(
    "field,from_value,to_value",
    [
        ("cik", "0000320193", "0000789019"),
        ("statement_type", StatementType.INCOME_STATEMENT, StatementType.BALANCE_SHEET),
        ("accounting_standard", AccountingStandard.US_GAAP, AccountingStandard.IFRS),
        ("statement_date", date(2024, 12, 31), date(2023, 12, 31)),
        ("fiscal_year", 2024, 2023),
        ("fiscal_period", FiscalPeriod.FY, FiscalPeriod.Q4),
        ("currency", "USD", "EUR"),
    ],
)
def test_compute_restatement_delta_raises_on_identity_mismatch(
    field: str,
    from_value: object,
    to_value: object,
) -> None:
    base_kwargs = dict(
        cik="0000320193",
        statement_type=StatementType.INCOME_STATEMENT,
        accounting_standard=AccountingStandard.US_GAAP,
        statement_date=date(2024, 12, 31),
        fiscal_year=2024,
        fiscal_period=FiscalPeriod.FY,
        currency="USD",
        core_metrics={CanonicalStatementMetric.REVENUE: Decimal("100")},
    )

    from_kwargs = dict(base_kwargs)
    to_kwargs = dict(base_kwargs)

    from_kwargs[field] = from_value
    to_kwargs[field] = to_value

    payload_v1 = _make_payload(**from_kwargs)
    payload_v2 = _make_payload(**to_kwargs)

    with pytest.raises(EdgarMappingError) as exc:
        compute_restatement_delta(from_payload=payload_v1, to_payload=payload_v2)

    assert "identity mismatch" in str(exc.value).lower()
