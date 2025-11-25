# tests/unit/application/use_cases/statements/test_get_fundamentals_timeseries_uc.py
# Copyright (c)
# SPDX-License-Identifier: MIT

from __future__ import annotations

from datetime import date
from decimal import Decimal
from typing import Any

import pytest

from stacklion_api.adapters.repositories.edgar_statements_repository import (
    EdgarStatementsRepository,
)
from stacklion_api.application.uow import UnitOfWork
from stacklion_api.application.use_cases.statements.get_fundamentals_timeseries import (
    GetFundamentalsTimeSeriesRequest,
    GetFundamentalsTimeSeriesUseCase,
)
from stacklion_api.domain.entities.canonical_statement_payload import (
    CanonicalStatementPayload,
)
from stacklion_api.domain.entities.edgar_company import EdgarCompanyIdentity
from stacklion_api.domain.entities.edgar_filing import EdgarFiling
from stacklion_api.domain.entities.edgar_fundamentals_timeseries import (
    FundamentalsTimeSeriesPoint,
)
from stacklion_api.domain.entities.edgar_statement_version import EdgarStatementVersion
from stacklion_api.domain.enums.canonical_statement_metric import CanonicalStatementMetric
from stacklion_api.domain.enums.edgar import (
    AccountingStandard,
    FilingType,
    FiscalPeriod,
    StatementType,
)
from stacklion_api.domain.exceptions.edgar import EdgarMappingError


class FakeUnitOfWork(UnitOfWork):  # type: ignore[misc]
    def __init__(self, repo: EdgarStatementsRepository) -> None:
        self._repo = repo

    async def __aenter__(self) -> FakeUnitOfWork:  # type: ignore[override]
        return self

    async def __aexit__(self, exc_type, exc, tb) -> None:  # type: ignore[override]
        return None

    def get_repository(self, repo_type: type[Any]) -> Any:  # type: ignore[override]
        assert repo_type is EdgarStatementsRepository
        return self._repo

    async def commit(self) -> None:  # pragma: no cover - not used
        return None

    async def rollback(self) -> None:  # pragma: no cover - not used
        return None


class FakeEdgarStatementsRepository(EdgarStatementsRepository):  # type: ignore[misc]
    def __init__(self, versions: list[EdgarStatementVersion]) -> None:
        self._versions = versions

    async def list_statement_versions_for_company(  # type: ignore[override]
        self,
        *,
        cik: str,
        statement_type: StatementType,
        fiscal_year: int,
        fiscal_period: FiscalPeriod | None = None,
    ) -> list[EdgarStatementVersion]:
        return [
            v
            for v in self._versions
            if v.company.cik == cik
            and v.statement_type is statement_type
            and v.fiscal_year == fiscal_year
            and (fiscal_period is None or v.fiscal_period is fiscal_period)
        ]


def _make_company(cik: str, name: str) -> EdgarCompanyIdentity:
    return EdgarCompanyIdentity(
        cik=cik,
        ticker=None,
        legal_name=name,
        exchange=None,
        country=None,
    )


def _make_filing(company: EdgarCompanyIdentity, accession: str) -> EdgarFiling:
    return EdgarFiling(
        accession_id=accession,
        company=company,
        filing_type=FilingType.FORM_10_K,
        filing_date=date(2024, 2, 1),
        period_end_date=date(2023, 12, 31),
        accepted_at=None,
        is_amendment=False,
        amendment_sequence=None,
        primary_document="doc.htm",
        data_source="edgar",
    )


def _make_payload(
    *,
    cik: str,
    statement_date: date,
    fiscal_year: int,
    fiscal_period: FiscalPeriod,
    version_sequence: int,
    revenue: str,
) -> CanonicalStatementPayload:
    return CanonicalStatementPayload(
        cik=cik,
        statement_type=StatementType.INCOME_STATEMENT,
        accounting_standard=AccountingStandard.US_GAAP,
        statement_date=statement_date,
        fiscal_year=fiscal_year,
        fiscal_period=fiscal_period,
        currency="USD",
        unit_multiplier=1,
        core_metrics={CanonicalStatementMetric.REVENUE: Decimal(revenue)},
        extra_metrics={},
        dimensions={},
        source_accession_id="acc",
        source_taxonomy="us-gaap-2024",
        source_version_sequence=version_sequence,
    )


def _make_version(
    *,
    company: EdgarCompanyIdentity,
    filing: EdgarFiling,
    statement_date: date,
    fiscal_year: int,
    fiscal_period: FiscalPeriod,
    version_sequence: int,
    revenue: str,
    with_payload: bool = True,
) -> EdgarStatementVersion:
    payload = (
        _make_payload(
            cik=company.cik,
            statement_date=statement_date,
            fiscal_year=fiscal_year,
            fiscal_period=fiscal_period,
            version_sequence=version_sequence,
            revenue=revenue,
        )
        if with_payload
        else None
    )

    return EdgarStatementVersion(
        company=company,
        filing=filing,
        statement_type=StatementType.INCOME_STATEMENT,
        accounting_standard=AccountingStandard.US_GAAP,
        statement_date=statement_date,
        fiscal_year=fiscal_year,
        fiscal_period=fiscal_period,
        currency="USD",
        is_restated=version_sequence > 1,
        restatement_reason="restated" if version_sequence > 1 else None,
        version_source="EDGAR_XBRL_NORMALIZED",
        version_sequence=version_sequence,
        accession_id=filing.accession_id,
        filing_date=filing.filing_date,
        normalized_payload=payload,
        normalized_payload_version="v1" if with_payload else None,
    )


@pytest.mark.anyio
async def test_get_fundamentals_timeseries_happy_path_annual() -> None:
    # Two companies, two years of FY data with normalized payloads.
    c1 = _make_company("0000320193", "Apple Inc.")
    c2 = _make_company("0000789019", "Microsoft Corp.")
    f1 = _make_filing(c1, "acc-1")
    f2 = _make_filing(c2, "acc-2")

    v1 = _make_version(
        company=c1,
        filing=f1,
        statement_date=date(2023, 12, 31),
        fiscal_year=2023,
        fiscal_period=FiscalPeriod.FY,
        version_sequence=1,
        revenue="100",
    )
    v2 = _make_version(
        company=c1,
        filing=f1,
        statement_date=date(2024, 12, 31),
        fiscal_year=2024,
        fiscal_period=FiscalPeriod.FY,
        version_sequence=1,
        revenue="110",
    )
    v3 = _make_version(
        company=c2,
        filing=f2,
        statement_date=date(2024, 12, 31),
        fiscal_year=2024,
        fiscal_period=FiscalPeriod.FY,
        version_sequence=1,
        revenue="200",
    )

    repo = FakeEdgarStatementsRepository([v1, v2, v3])
    uow = FakeUnitOfWork(repo)
    uc = GetFundamentalsTimeSeriesUseCase(uow=uow)

    req = GetFundamentalsTimeSeriesRequest(
        ciks=["0000320193", "0000789019"],
        statement_type=StatementType.INCOME_STATEMENT,
        metrics=[CanonicalStatementMetric.REVENUE],
        frequency="annual",
        from_date=date(2023, 1, 1),
        to_date=date(2024, 12, 31),
    )

    series = await uc.execute(req)

    assert all(isinstance(p, FundamentalsTimeSeriesPoint) for p in series)
    # Expect three points: c1-2023, c1-2024, c2-2024
    assert [p.cik for p in series] == ["0000320193", "0000320193", "0000789019"]
    assert [p.statement_date for p in series] == [
        date(2023, 12, 31),
        date(2024, 12, 31),
        date(2024, 12, 31),
    ]
    assert [p.metrics[CanonicalStatementMetric.REVENUE] for p in series] == [
        Decimal("100"),
        Decimal("110"),
        Decimal("200"),
    ]


@pytest.mark.anyio
async def test_get_fundamentals_timeseries_keeps_latest_version_per_period() -> None:
    c1 = _make_company("0000320193", "Apple Inc.")
    f1 = _make_filing(c1, "acc-1")

    # Two versions for the same FY period; we expect only version_sequence=2.
    v1 = _make_version(
        company=c1,
        filing=f1,
        statement_date=date(2024, 12, 31),
        fiscal_year=2024,
        fiscal_period=FiscalPeriod.FY,
        version_sequence=1,
        revenue="100",
    )
    v2 = _make_version(
        company=c1,
        filing=f1,
        statement_date=date(2024, 12, 31),
        fiscal_year=2024,
        fiscal_period=FiscalPeriod.FY,
        version_sequence=2,
        revenue="110",
    )

    repo = FakeEdgarStatementsRepository([v1, v2])
    uow = FakeUnitOfWork(repo)
    uc = GetFundamentalsTimeSeriesUseCase(uow=uow)

    req = GetFundamentalsTimeSeriesRequest(
        ciks=["0000320193"],
        statement_type=StatementType.INCOME_STATEMENT,
        metrics=[CanonicalStatementMetric.REVENUE],
        frequency="annual",
        from_date=date(2024, 1, 1),
        to_date=date(2024, 12, 31),
    )

    series = await uc.execute(req)

    assert len(series) == 1
    point = series[0]
    assert point.cik == "0000320193"
    assert point.statement_date == date(2024, 12, 31)
    assert point.metrics[CanonicalStatementMetric.REVENUE] == Decimal("110")


@pytest.mark.anyio
async def test_get_fundamentals_timeseries_validates_inputs() -> None:
    repo = FakeEdgarStatementsRepository([])
    uow = FakeUnitOfWork(repo)
    uc = GetFundamentalsTimeSeriesUseCase(uow=uow)

    # Empty universe
    req_empty_universe = GetFundamentalsTimeSeriesRequest(
        ciks=["  "],
        statement_type=StatementType.INCOME_STATEMENT,
        metrics=None,
        frequency="annual",
        from_date=None,
        to_date=None,
    )
    with pytest.raises(EdgarMappingError):
        await uc.execute(req_empty_universe)

    # Invalid frequency
    req_bad_frequency = GetFundamentalsTimeSeriesRequest(
        ciks=["0000320193"],
        statement_type=StatementType.INCOME_STATEMENT,
        metrics=None,
        frequency="monthly",
        from_date=None,
        to_date=None,
    )
    with pytest.raises(EdgarMappingError):
        await uc.execute(req_bad_frequency)

    # Inverted date window
    req_bad_window = GetFundamentalsTimeSeriesRequest(
        ciks=["0000320193"],
        statement_type=StatementType.INCOME_STATEMENT,
        metrics=None,
        frequency="annual",
        from_date=date(2025, 1, 1),
        to_date=date(2024, 1, 1),
    )
    with pytest.raises(EdgarMappingError):
        await uc.execute(req_bad_window)
