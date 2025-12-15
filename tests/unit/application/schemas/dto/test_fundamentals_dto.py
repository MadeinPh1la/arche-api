# tests/unit/application/schemas/dto/test_fundamentals_dto.py
# Copyright (c)
# SPDX-License-Identifier: MIT

from __future__ import annotations

from datetime import date

from arche_api.application.schemas.dto.fundamentals import (
    FundamentalsTimeSeriesPointDTO,
    GetFundamentalsTimeSeriesResultDTO,
)


def test_fundamentals_timeseries_point_dto_roundtrip() -> None:
    dto = FundamentalsTimeSeriesPointDTO(
        cik="0000320193",
        statement_date=date(2024, 12, 31),
        fiscal_year=2024,
        fiscal_period="FY",  # Pydantic will coerce to FiscalPeriod.FY
        frequency="annual",
        metrics={
            "revenue": "123.45",
            "net_income": None,
        },
    )

    assert dto.cik == "0000320193"
    assert dto.statement_date == date(2024, 12, 31)
    assert dto.fiscal_year == 2024
    assert dto.fiscal_period.value == "FY"
    assert dto.frequency == "annual"
    assert dto.metrics["revenue"] == "123.45"
    assert "net_income" in dto.metrics
    assert dto.metrics["net_income"] is None


def test_get_fundamentals_timeseries_result_dto_wraps_points() -> None:
    point = FundamentalsTimeSeriesPointDTO(
        cik="0000320193",
        statement_date=date(2024, 12, 31),
        fiscal_year=2024,
        fiscal_period="FY",
        frequency="annual",
        metrics={"revenue": "123.45"},
    )

    result = GetFundamentalsTimeSeriesResultDTO(points=[point])

    assert len(result.points) == 1
    wrapped = result.points[0]
    assert wrapped.cik == "0000320193"
    assert wrapped.metrics["revenue"] == "123.45"
