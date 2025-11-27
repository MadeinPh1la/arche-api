# tests/unit/application/use_cases/statements/test_compute_restatement_delta_uc.py
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
from stacklion_api.application.use_cases.statements.compute_restatement_delta import (
    ComputeRestatementDeltaRequest,
    ComputeRestatementDeltaUseCase,
)
from stacklion_api.domain.entities.canonical_statement_payload import (
    CanonicalStatementPayload,
)
from stacklion_api.domain.entities.edgar_company import EdgarCompanyIdentity
from stacklion_api.domain.entities.edgar_filing import EdgarFiling
from stacklion_api.domain.entities.edgar_statement_version import EdgarStatementVersion
from stacklion_api.domain.enums.canonical_statement_metric import CanonicalStatementMetric
from stacklion_api.domain.enums.edgar import (
    AccountingStandard,
    FilingType,
    FiscalPeriod,
    StatementType,
)
from stacklion_api.domain.exceptions.edgar import EdgarIngestionError, EdgarMappingError


class FakeUnitOfWork(UnitOfWork):  # type: ignore[misc]
    def __init__(self, repo: EdgarStatementsRepository) -> None:
        self._repo = repo

    async def __aenter__(self) -> FakeUnitOfWork:  # type: ignore[override]
        return self

    async def __aexit__(self, exc_type, exc, tb) -> None:  # type: ignore[override]
        return None

    def get_repository(self, repo_type: type[Any]) -> Any:  # type: ignore[override]
        # In tests we don't care which key is requested; always return the fake repo.
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


def _make_payload(version_sequence: int, revenue: str) -> CanonicalStatementPayload:
    return CanonicalStatementPayload(
        cik="0000320193",
        statement_type=StatementType.INCOME_STATEMENT,
        accounting_standard=AccountingStandard.US_GAAP,
        statement_date=date(2024, 9, 28),
        fiscal_year=2024,
        fiscal_period=FiscalPeriod.FY,
        currency="USD",
        unit_multiplier=1,
        core_metrics={CanonicalStatementMetric.REVENUE: Decimal(revenue)},
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
    with_payload: bool = True,
) -> EdgarStatementVersion:
    payload = (
        _make_payload(version_sequence=version_sequence, revenue=revenue) if with_payload else None
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
async def test_compute_restatement_delta_use_case_happy_path() -> None:
    company = _make_company()
    filing = _make_filing(company)
    v1 = _make_version(company=company, filing=filing, version_sequence=1, revenue="100")
    v2 = _make_version(company=company, filing=filing, version_sequence=2, revenue="120")

    repo = FakeEdgarStatementsRepository([v1, v2])
    uow = FakeUnitOfWork(repo)
    uc = ComputeRestatementDeltaUseCase(uow=uow)

    req = ComputeRestatementDeltaRequest(
        cik="0000320193",
        statement_type=StatementType.INCOME_STATEMENT,
        fiscal_year=2024,
        fiscal_period=FiscalPeriod.FY,
        from_version_sequence=1,
        to_version_sequence=2,
        metrics=None,
    )

    result = await uc.execute(req)

    assert result.from_version.version_sequence == 1
    assert result.to_version.version_sequence == 2

    delta = result.delta
    assert delta.from_version_sequence == 1
    assert delta.to_version_sequence == 2
    assert CanonicalStatementMetric.REVENUE in delta.metrics
    metric_delta = delta.metrics[CanonicalStatementMetric.REVENUE]
    assert metric_delta.old == Decimal("100")
    assert metric_delta.new == Decimal("120")
    assert metric_delta.diff == Decimal("20")


@pytest.mark.anyio
async def test_compute_restatement_delta_use_case_raises_on_missing_versions() -> None:
    # Only one version exists; the "to" version is missing.
    company = _make_company()
    filing = _make_filing(company)
    v1 = _make_version(company=company, filing=filing, version_sequence=1, revenue="100")

    repo = FakeEdgarStatementsRepository([v1])
    uow = FakeUnitOfWork(repo)
    uc = ComputeRestatementDeltaUseCase(uow=uow)

    req = ComputeRestatementDeltaRequest(
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
async def test_compute_restatement_delta_use_case_raises_when_payload_missing() -> None:
    company = _make_company()
    filing = _make_filing(company)
    v1 = _make_version(
        company=company,
        filing=filing,
        version_sequence=1,
        revenue="100",
        with_payload=False,
    )
    v2 = _make_version(company=company, filing=filing, version_sequence=2, revenue="120")

    repo = FakeEdgarStatementsRepository([v1, v2])
    uow = FakeUnitOfWork(repo)
    uc = ComputeRestatementDeltaUseCase(uow=uow)

    req = ComputeRestatementDeltaRequest(
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
async def test_compute_restatement_delta_use_case_validates_request_fields() -> None:
    repo = FakeEdgarStatementsRepository([])
    uow = FakeUnitOfWork(repo)
    uc = ComputeRestatementDeltaUseCase(uow=uow)

    # Empty CIK
    bad_cik = ComputeRestatementDeltaRequest(
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

    # Non-positive fiscal year
    bad_year = ComputeRestatementDeltaRequest(
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

    # Invalid version ordering
    bad_versions = ComputeRestatementDeltaRequest(
        cik="0000320193",
        statement_type=StatementType.INCOME_STATEMENT,
        fiscal_year=2024,
        fiscal_period=FiscalPeriod.FY,
        from_version_sequence=2,
        to_version_sequence=1,
        metrics=None,
    )
    with pytest.raises(EdgarMappingError):
        await uc.execute(bad_versions)
