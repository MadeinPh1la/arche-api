# tests/unit/application/use_cases/test_get_restatement_delta_between_versions.py
# Copyright (c)
# SPDX-License-Identifier: MIT

from __future__ import annotations

from datetime import date
from decimal import Decimal
from typing import Any

import pytest

from arche_api.application.uow import UnitOfWork
from arche_api.application.use_cases.statements.get_restatement_delta_between_versions import (
    GetRestatementDeltaBetweenVersionsRequest,
    GetRestatementDeltaBetweenVersionsUseCase,
)
from arche_api.domain.entities.canonical_statement_payload import (
    CanonicalStatementPayload,
)
from arche_api.domain.entities.edgar_company import EdgarCompanyIdentity
from arche_api.domain.entities.edgar_filing import EdgarFiling
from arche_api.domain.entities.edgar_statement_version import EdgarStatementVersion
from arche_api.domain.enums.canonical_statement_metric import CanonicalStatementMetric
from arche_api.domain.enums.edgar import (
    AccountingStandard,
    FilingType,
    FiscalPeriod,
    StatementType,
)
from arche_api.domain.exceptions.edgar import EdgarIngestionError, EdgarMappingError
from arche_api.domain.interfaces.repositories.edgar_statements_repository import (
    EdgarStatementsRepository,
)


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


class FakeUnitOfWork(UnitOfWork):  # type: ignore[misc]
    def __init__(self, repo: FakeEdgarStatementsRepository) -> None:
        self._repo = repo

    async def __aenter__(self) -> FakeUnitOfWork:  # type: ignore[override]
        return self

    async def __aexit__(self, exc_type, exc, tb) -> None:  # type: ignore[override]
        return None

    def get_repository(self, repo_type: type[Any]) -> Any:  # type: ignore[override]
        return self._repo

    async def commit(self) -> None:  # pragma: no cover
        return None

    async def rollback(self) -> None:  # pragma: no cover
        return None


def _make_company() -> EdgarCompanyIdentity:
    return EdgarCompanyIdentity(
        cik="0000320193",
        ticker="AAPL",
        legal_name="Apple Inc.",
        exchange=None,
        country=None,
    )


def _make_filing(company: EdgarCompanyIdentity) -> EdgarFiling:
    return EdgarFiling(
        accession_id="0000320193-24-000012",
        company=company,
        filing_type=FilingType.FORM_10_K,
        filing_date=date(2024, 10, 25),
        period_end_date=date(2024, 9, 28),
        accepted_at=None,
        is_amendment=False,
        amendment_sequence=None,
        primary_document="aapl-20240928.htm",
        data_source="edgar",
    )


def _make_payload(
    version_sequence: int, revenue: str, net_income: str | None = None
) -> CanonicalStatementPayload:  # noqa: E501
    metrics: dict[CanonicalStatementMetric, Decimal] = {
        CanonicalStatementMetric.REVENUE: Decimal(revenue),
    }
    if net_income is not None:
        metrics[CanonicalStatementMetric.NET_INCOME] = Decimal(net_income)

    return CanonicalStatementPayload(
        cik="0000320193",
        statement_type=StatementType.INCOME_STATEMENT,
        accounting_standard=AccountingStandard.US_GAAP,
        statement_date=date(2024, 9, 28),
        fiscal_year=2024,
        fiscal_period=FiscalPeriod.FY,
        currency="USD",
        unit_multiplier=1,
        core_metrics=metrics,
        extra_metrics={},
        dimensions={},
        source_accession_id="0000320193-24-000012",
        source_taxonomy="us-gaap-2024",
        source_version_sequence=version_sequence,
    )


def _make_version(
    *,
    company: EdgarCompanyIdentity,
    filing: EdgarFiling,
    version_sequence: int,
    revenue: str,
    net_income: str | None = None,
    with_payload: bool = True,
) -> EdgarStatementVersion:
    payload = (
        _make_payload(
            version_sequence=version_sequence,
            revenue=revenue,
            net_income=net_income,
        )
        if with_payload
        else None
    )
    return EdgarStatementVersion(
        company=company,
        filing=filing,
        statement_type=StatementType.INCOME_STATEMENT,
        accounting_standard=AccountingStandard.US_GAAP,
        statement_date=date(2024, 9, 28),
        fiscal_year=2024,
        fiscal_period=FiscalPeriod.FY,
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
async def test_get_restatement_delta_between_versions_happy_path() -> None:
    company = _make_company()
    filing = _make_filing(company)
    v1 = _make_version(
        company=company,
        filing=filing,
        version_sequence=1,
        revenue="100",
        net_income="10",
    )
    v2 = _make_version(
        company=company,
        filing=filing,
        version_sequence=2,
        revenue="120",
        net_income="15",
    )

    repo = FakeEdgarStatementsRepository([v1, v2])
    uow = FakeUnitOfWork(repo)
    uc = GetRestatementDeltaBetweenVersionsUseCase(uow=uow)

    req = GetRestatementDeltaBetweenVersionsRequest(
        cik="0000320193",
        statement_type=StatementType.INCOME_STATEMENT,
        fiscal_year=2024,
        fiscal_period=FiscalPeriod.FY,
        from_version_sequence=1,
        to_version_sequence=2,
        metrics=None,
    )

    result = await uc.execute(req)

    assert result.cik == "0000320193"
    assert result.statement_type is StatementType.INCOME_STATEMENT
    assert result.fiscal_year == 2024
    assert result.fiscal_period is FiscalPeriod.FY
    assert result.from_version_sequence == 1
    assert result.to_version_sequence == 2

    # At least REVENUE should be present and changed.
    metrics = {d.metric: d for d in result.deltas}
    assert "REVENUE" in metrics
    revenue_delta = metrics["REVENUE"]
    assert revenue_delta.old_value == "100"
    assert revenue_delta.new_value == "120"
    assert revenue_delta.diff == "20"

    assert result.summary.total_metrics_changed >= 1
    assert result.summary.total_metrics_compared == result.summary.total_metrics_changed
    assert result.summary.has_material_change is True


@pytest.mark.anyio
async def test_get_restatement_delta_between_versions_applies_metric_filter() -> None:
    company = _make_company()
    filing = _make_filing(company)
    v1 = _make_version(
        company=company,
        filing=filing,
        version_sequence=1,
        revenue="100",
        net_income="10",
    )
    v2 = _make_version(
        company=company,
        filing=filing,
        version_sequence=2,
        revenue="120",
        net_income="15",
    )

    repo = FakeEdgarStatementsRepository([v1, v2])
    uow = FakeUnitOfWork(repo)
    uc = GetRestatementDeltaBetweenVersionsUseCase(uow=uow)

    req = GetRestatementDeltaBetweenVersionsRequest(
        cik="0000320193",
        statement_type=StatementType.INCOME_STATEMENT,
        fiscal_year=2024,
        fiscal_period=FiscalPeriod.FY,
        from_version_sequence=1,
        to_version_sequence=2,
        metrics=[CanonicalStatementMetric.NET_INCOME],
    )

    result = await uc.execute(req)

    metric_names = {d.metric for d in result.deltas}
    assert metric_names == {"NET_INCOME"}


@pytest.mark.anyio
async def test_get_restatement_delta_between_versions_raises_on_no_versions() -> None:
    repo = FakeEdgarStatementsRepository([])
    uow = FakeUnitOfWork(repo)
    uc = GetRestatementDeltaBetweenVersionsUseCase(uow=uow)

    req = GetRestatementDeltaBetweenVersionsRequest(
        cik="0000320193",
        statement_type=StatementType.INCOME_STATEMENT,
        fiscal_year=2024,
        fiscal_period=FiscalPeriod.FY,
        from_version_sequence=1,
        to_version_sequence=2,
        metrics=None,
    )

    with pytest.raises(EdgarIngestionError):
        await uc.execute(req)


@pytest.mark.anyio
async def test_get_restatement_delta_between_versions_raises_on_insufficient_normalized_versions() -> (
    None
):  # noqa: E501
    company = _make_company()
    filing = _make_filing(company)
    v1 = _make_version(
        company=company,
        filing=filing,
        version_sequence=1,
        revenue="100",
        with_payload=True,
    )
    v2 = _make_version(
        company=company,
        filing=filing,
        version_sequence=2,
        revenue="120",
        with_payload=False,
    )

    repo = FakeEdgarStatementsRepository([v1, v2])
    uow = FakeUnitOfWork(repo)
    uc = GetRestatementDeltaBetweenVersionsUseCase(uow=uow)

    req = GetRestatementDeltaBetweenVersionsRequest(
        cik="0000320193",
        statement_type=StatementType.INCOME_STATEMENT,
        fiscal_year=2024,
        fiscal_period=FiscalPeriod.FY,
        from_version_sequence=1,
        to_version_sequence=2,
        metrics=None,
    )

    with pytest.raises(EdgarIngestionError):
        await uc.execute(req)


@pytest.mark.anyio
async def test_get_restatement_delta_between_versions_validates_request_fields() -> None:
    repo = FakeEdgarStatementsRepository([])
    uow = FakeUnitOfWork(repo)
    uc = GetRestatementDeltaBetweenVersionsUseCase(uow=uow)

    bad_cik = GetRestatementDeltaBetweenVersionsRequest(
        cik="  ",
        statement_type=StatementType.INCOME_STATEMENT,
        fiscal_year=2024,
        fiscal_period=FiscalPeriod.FY,
        from_version_sequence=1,
        to_version_sequence=2,
        metrics=None,
    )
    with pytest.raises(EdgarMappingError):
        await uc.execute(bad_cik)

    bad_year = GetRestatementDeltaBetweenVersionsRequest(
        cik="0000320193",
        statement_type=StatementType.INCOME_STATEMENT,
        fiscal_year=0,
        fiscal_period=FiscalPeriod.FY,
        from_version_sequence=1,
        to_version_sequence=2,
        metrics=None,
    )
    with pytest.raises(EdgarMappingError):
        await uc.execute(bad_year)

    bad_from = GetRestatementDeltaBetweenVersionsRequest(
        cik="0000320193",
        statement_type=StatementType.INCOME_STATEMENT,
        fiscal_year=2024,
        fiscal_period=FiscalPeriod.FY,
        from_version_sequence=0,
        to_version_sequence=2,
        metrics=None,
    )
    with pytest.raises(EdgarMappingError):
        await uc.execute(bad_from)

    bad_to = GetRestatementDeltaBetweenVersionsRequest(
        cik="0000320193",
        statement_type=StatementType.INCOME_STATEMENT,
        fiscal_year=2024,
        fiscal_period=FiscalPeriod.FY,
        from_version_sequence=1,
        to_version_sequence=0,
        metrics=None,
    )
    with pytest.raises(EdgarMappingError):
        await uc.execute(bad_to)
