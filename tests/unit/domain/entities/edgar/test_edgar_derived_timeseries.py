# tests/unit/domain/entities/test_edgar_derived_timeseries.py
# Copyright (c)
# SPDX-License-Identifier: MIT

from __future__ import annotations

from datetime import date
from decimal import Decimal

import pytest

from stacklion_api.domain.entities.edgar_derived_timeseries import (
    DerivedMetricsTimeSeriesPoint,
    build_derived_metrics_timeseries,
)
from stacklion_api.domain.enums.derived_metric import DerivedMetric
from stacklion_api.domain.enums.edgar import AccountingStandard, FiscalPeriod, StatementType


def _make_point(
    *,
    cik: str = "0000320193",
    statement_date: date = date(2024, 12, 31),
    fiscal_year: int = 2024,
    fiscal_period: FiscalPeriod = FiscalPeriod.FY,
    version_sequence: int = 1,
    metric_value: Decimal = Decimal("0.4"),
) -> DerivedMetricsTimeSeriesPoint:
    return DerivedMetricsTimeSeriesPoint(
        cik=cik,
        statement_type=StatementType.INCOME_STATEMENT,
        accounting_standard=AccountingStandard.US_GAAP,
        statement_date=statement_date,
        fiscal_year=fiscal_year,
        fiscal_period=fiscal_period,
        currency="USD",
        metrics={DerivedMetric.GROSS_MARGIN: metric_value},
        normalized_payload_version_sequence=version_sequence,
    )


def test_build_derived_metrics_timeseries_orders_points() -> None:
    # Same CIK/date/period, different version sequences -> sorted by sequence.
    p2 = _make_point(version_sequence=2, metric_value=Decimal("0.5"))
    p1 = _make_point(version_sequence=1, metric_value=Decimal("0.3"))

    series = build_derived_metrics_timeseries([p2, p1])

    assert [p.normalized_payload_version_sequence for p in series] == [1, 2]
    assert [p.metrics[DerivedMetric.GROSS_MARGIN] for p in series] == [
        Decimal("0.3"),
        Decimal("0.5"),
    ]


def test_point_validates_cik_non_empty() -> None:
    with pytest.raises(ValueError):
        _make_point(cik="")

    with pytest.raises(ValueError):
        _make_point(cik="   ")


def test_point_validates_fiscal_year_positive() -> None:
    with pytest.raises(ValueError):
        _make_point(fiscal_year=0)

    with pytest.raises(ValueError):
        _make_point(fiscal_year=-1)


def test_point_validates_version_sequence_positive() -> None:
    with pytest.raises(ValueError):
        _make_point(version_sequence=0)

    with pytest.raises(ValueError):
        _make_point(version_sequence=-3)


def test_point_validates_metrics_key_type() -> None:
    # Non-DerivedMetric key should raise.
    with pytest.raises(ValueError):
        DerivedMetricsTimeSeriesPoint(
            cik="0000320193",
            statement_type=StatementType.INCOME_STATEMENT,
            accounting_standard=AccountingStandard.US_GAAP,
            statement_date=date(2024, 12, 31),
            fiscal_year=2024,
            fiscal_period=FiscalPeriod.FY,
            currency="USD",
            metrics={"NOT_A_METRIC": Decimal("0.4")},  # type: ignore[arg-type]
            normalized_payload_version_sequence=1,
        )


def test_point_validates_metrics_value_type() -> None:
    # Non-Decimal, non-None value should raise.
    with pytest.raises(ValueError):
        DerivedMetricsTimeSeriesPoint(
            cik="0000320193",
            statement_type=StatementType.INCOME_STATEMENT,
            accounting_standard=AccountingStandard.US_GAAP,
            statement_date=date(2024, 12, 31),
            fiscal_year=2024,
            fiscal_period=FiscalPeriod.FY,
            currency="USD",
            metrics={DerivedMetric.GROSS_MARGIN: "0.4"},  # type: ignore[dict-item]
            normalized_payload_version_sequence=1,
        )
