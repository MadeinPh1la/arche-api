# tests/unit/domain/test_edgar_fundamentals_timeseries.py
# Copyright (c)
# SPDX-License-Identifier: MIT

from __future__ import annotations

from datetime import date
from decimal import Decimal

from arche_api.domain.entities.canonical_statement_payload import (
    CanonicalStatementPayload,
)
from arche_api.domain.entities.edgar_fundamentals_timeseries import (
    FundamentalsTimeSeriesPoint,
    build_fundamentals_timeseries,
)
from arche_api.domain.enums.canonical_statement_metric import CanonicalStatementMetric
from arche_api.domain.enums.edgar import AccountingStandard, FiscalPeriod, StatementType


def _make_payload(
    *,
    cik: str,
    statement_date: date,
    fiscal_year: int,
    fiscal_period: FiscalPeriod,
    source_version_sequence: int,
    revenue: str,
    net_income: str | None = None,
) -> CanonicalStatementPayload:
    core: dict[CanonicalStatementMetric, Decimal] = {
        CanonicalStatementMetric.REVENUE: Decimal(revenue),
    }
    if net_income is not None:
        core[CanonicalStatementMetric.NET_INCOME] = Decimal(net_income)

    return CanonicalStatementPayload(
        cik=cik,
        statement_type=StatementType.INCOME_STATEMENT,
        accounting_standard=AccountingStandard.US_GAAP,
        statement_date=statement_date,
        fiscal_year=fiscal_year,
        fiscal_period=fiscal_period,
        currency="USD",
        unit_multiplier=1,
        core_metrics=core,
        extra_metrics={},
        dimensions={},
        source_accession_id="acc",
        source_taxonomy="us-gaap",
        source_version_sequence=source_version_sequence,
    )


def test_build_fundamentals_timeseries_orders_points_deterministically() -> None:
    payloads = [
        _make_payload(
            cik="0000320193",
            statement_date=date(2024, 3, 31),
            fiscal_year=2024,
            fiscal_period=FiscalPeriod.Q1,
            source_version_sequence=2,
            revenue="110",
        ),
        _make_payload(
            cik="0000320193",
            statement_date=date(2023, 12, 31),
            fiscal_year=2023,
            fiscal_period=FiscalPeriod.FY,
            source_version_sequence=1,
            revenue="100",
        ),
        _make_payload(
            cik="0000789019",
            statement_date=date(2024, 12, 31),
            fiscal_year=2024,
            fiscal_period=FiscalPeriod.FY,
            source_version_sequence=1,
            revenue="200",
        ),
    ]

    series = build_fundamentals_timeseries(payloads=payloads)

    assert all(isinstance(p, FundamentalsTimeSeriesPoint) for p in series)
    # Ordering: by cik, then statement_date, then fiscal_year, fiscal_period, version
    assert [p.cik for p in series] == [
        "0000320193",
        "0000320193",
        "0000789019",
    ]
    assert [p.statement_date for p in series] == [
        date(2023, 12, 31),
        date(2024, 3, 31),
        date(2024, 12, 31),
    ]


def test_build_fundamentals_timeseries_respects_metric_filter() -> None:
    payload = _make_payload(
        cik="0000320193",
        statement_date=date(2024, 12, 31),
        fiscal_year=2024,
        fiscal_period=FiscalPeriod.FY,
        source_version_sequence=1,
        revenue="100",
        net_income="10",
    )

    series = build_fundamentals_timeseries(
        payloads=[payload],
        metrics=[CanonicalStatementMetric.NET_INCOME],
    )

    assert len(series) == 1
    point = series[0]
    assert CanonicalStatementMetric.REVENUE not in point.metrics
    assert point.metrics[CanonicalStatementMetric.NET_INCOME] == Decimal("10")


def test_build_fundamentals_timeseries_omits_missing_metrics() -> None:
    payload = _make_payload(
        cik="0000320193",
        statement_date=date(2024, 12, 31),
        fiscal_year=2024,
        fiscal_period=FiscalPeriod.FY,
        source_version_sequence=1,
        revenue="100",
        net_income=None,
    )

    series = build_fundamentals_timeseries(
        payloads=[payload],
        metrics=[CanonicalStatementMetric.NET_INCOME],
    )

    assert len(series) == 1
    point = series[0]
    assert CanonicalStatementMetric.NET_INCOME not in point.metrics
