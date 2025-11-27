# tests/unit/application/use_cases/statements/test_get_normalized_statement.py
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
from stacklion_api.application.use_cases.statements.get_normalized_statement import (
    GetNormalizedStatementRequest,
    GetNormalizedStatementUseCase,
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
    """Minimal fake UnitOfWork for testing read-only use cases."""

    def __init__(self, repo: EdgarStatementsRepository) -> None:
        self._repo = repo
        self._entered = False

    async def __aenter__(self) -> FakeUnitOfWork:  # type: ignore[override]
        self._entered = True
        return self

    async def __aexit__(self, exc_type, exc, tb) -> None:  # type: ignore[override]
        self._entered = False

    def get_repository(self, repo_type: type[Any]) -> Any:  # type: ignore[override]
        # Tests only care that a repo is returned; ignore the key.
        return self._repo

    async def commit(self) -> None:  # pragma: no cover - not used in this UC
        return None

    async def rollback(self) -> None:  # pragma: no cover - not used in this UC
        return None


class FakeEdgarStatementsRepository(EdgarStatementsRepository):  # type: ignore[misc]
    """Fake repository returning in-memory statement versions."""

    def __init__(self, versions: list[EdgarStatementVersion]) -> None:
        # We do not call BaseRepository.__init__ or pass a real session.
        self._versions = versions

    async def latest_statement_version_for_company(  # type: ignore[override]
        self,
        *,
        cik: str,
        statement_type: StatementType,
        fiscal_year: int,
        fiscal_period: FiscalPeriod,
    ) -> EdgarStatementVersion | None:
        candidates = [
            v
            for v in self._versions
            if v.company.cik == cik
            and v.statement_type is statement_type
            and v.fiscal_year == fiscal_year
            and v.fiscal_period is fiscal_period
        ]
        if not candidates:
            return None
        return max(candidates, key=lambda v: v.version_sequence)

    async def list_statement_versions_for_company(  # type: ignore[override]
        self,
        *,
        cik: str,
        statement_type: StatementType,
        fiscal_year: int,
        fiscal_period: FiscalPeriod | None = None,
    ) -> list[EdgarStatementVersion]:
        results = [
            v
            for v in self._versions
            if v.company.cik == cik
            and v.statement_type is statement_type
            and v.fiscal_year == fiscal_year
            and (fiscal_period is None or v.fiscal_period is fiscal_period)
        ]
        return sorted(results, key=lambda v: (v.version_sequence, v.accession_id))


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


def _make_payload(version_sequence: int) -> CanonicalStatementPayload:
    return CanonicalStatementPayload(
        cik="0000320193",
        statement_type=StatementType.INCOME_STATEMENT,
        accounting_standard=AccountingStandard.US_GAAP,
        statement_date=date(2024, 9, 28),
        fiscal_year=2024,
        fiscal_period=FiscalPeriod.FY,
        currency="USD",
        unit_multiplier=1,
        core_metrics={CanonicalStatementMetric.REVENUE: Decimal("100.0")},
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
    normalized: bool,
) -> EdgarStatementVersion:
    normalized_payload = _make_payload(version_sequence) if normalized else None
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
        restatement_reason="restatement" if version_sequence > 1 else None,
        version_source="EDGAR_XBRL_NORMALIZED",
        version_sequence=version_sequence,
        accession_id=filing.accession_id,
        filing_date=filing.filing_date,
        normalized_payload=normalized_payload,
        normalized_payload_version="v1" if normalized else None,
    )


@pytest.mark.anyio
async def test_get_normalized_statement_happy_path_returns_latest_and_history() -> None:
    company = _make_company()
    filing = _make_filing(company)
    v1 = _make_version(company=company, filing=filing, version_sequence=1, normalized=True)
    v2 = _make_version(company=company, filing=filing, version_sequence=2, normalized=True)

    repo = FakeEdgarStatementsRepository([v1, v2])
    uow = FakeUnitOfWork(repo)
    uc = GetNormalizedStatementUseCase(uow=uow)

    req = GetNormalizedStatementRequest(
        cik="0000320193",
        statement_type=StatementType.INCOME_STATEMENT,
        fiscal_year=2024,
        fiscal_period=FiscalPeriod.FY,
        include_version_history=True,
    )

    result = await uc.execute(req)

    assert result.latest_version.version_sequence == 2
    assert result.latest_version.normalized_payload is not None
    assert [v.version_sequence for v in result.version_history] == [1, 2]


@pytest.mark.anyio
async def test_get_normalized_statement_raises_when_no_versions_found() -> None:
    repo = FakeEdgarStatementsRepository([])
    uow = FakeUnitOfWork(repo)
    uc = GetNormalizedStatementUseCase(uow=uow)

    req = GetNormalizedStatementRequest(
        cik="0000320193",
        statement_type=StatementType.INCOME_STATEMENT,
        fiscal_year=2024,
        fiscal_period=FiscalPeriod.FY,
    )

    with pytest.raises(EdgarIngestionError):
        await uc.execute(req)


@pytest.mark.anyio
async def test_get_normalized_statement_raises_when_latest_has_no_payload() -> None:
    company = _make_company()
    filing = _make_filing(company)
    v1 = _make_version(company=company, filing=filing, version_sequence=1, normalized=False)

    repo = FakeEdgarStatementsRepository([v1])
    uow = FakeUnitOfWork(repo)
    uc = GetNormalizedStatementUseCase(uow=uow)

    req = GetNormalizedStatementRequest(
        cik="0000320193",
        statement_type=StatementType.INCOME_STATEMENT,
        fiscal_year=2024,
        fiscal_period=FiscalPeriod.FY,
    )

    with pytest.raises(EdgarIngestionError):
        await uc.execute(req)


@pytest.mark.anyio
async def test_get_normalized_statement_validates_cik_and_fiscal_year() -> None:
    repo = FakeEdgarStatementsRepository([])
    uow = FakeUnitOfWork(repo)
    uc = GetNormalizedStatementUseCase(uow=uow)

    bad_req_empty_cik = GetNormalizedStatementRequest(
        cik="  ",
        statement_type=StatementType.INCOME_STATEMENT,
        fiscal_year=2024,
        fiscal_period=FiscalPeriod.FY,
    )

    with pytest.raises(EdgarMappingError):
        await uc.execute(bad_req_empty_cik)

    bad_req_year = GetNormalizedStatementRequest(
        cik="0000320193",
        statement_type=StatementType.INCOME_STATEMENT,
        fiscal_year=0,
        fiscal_period=FiscalPeriod.FY,
    )

    with pytest.raises(EdgarMappingError):
        await uc.execute(bad_req_year)
