# tests/unit/application/use_cases/test_get_restatement_ledger.py
# Copyright (c)
# SPDX-License-Identifier: MIT

from __future__ import annotations

from datetime import date
from decimal import Decimal
from typing import Any

import pytest

from arche_api.application.uow import UnitOfWork
from arche_api.application.use_cases.statements.get_restatement_ledger import (
    GetRestatementLedgerRequest,
    GetRestatementLedgerUseCase,
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
        # Fallback if _repo is not picked up by the use case helper.
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
async def test_get_restatement_ledger_happy_path() -> None:
    company = _make_company()
    filing = _make_filing(company)
    v1 = _make_version(company=company, filing=filing, version_sequence=1, revenue="100")
    v2 = _make_version(company=company, filing=filing, version_sequence=2, revenue="120")

    repo = FakeEdgarStatementsRepository([v1, v2])
    uow = FakeUnitOfWork(repo)
    uc = GetRestatementLedgerUseCase(uow=uow)

    req = GetRestatementLedgerRequest(
        cik="0000320193",
        statement_type=StatementType.INCOME_STATEMENT,
        fiscal_year=2024,
        fiscal_period=FiscalPeriod.FY,
    )

    result = await uc.execute(req)

    assert result.cik == "0000320193"
    assert result.statement_type is StatementType.INCOME_STATEMENT
    assert result.fiscal_year == 2024
    assert result.fiscal_period is FiscalPeriod.FY
    assert len(result.entries) == 1

    entry = result.entries[0]
    assert entry.from_version_sequence == 1
    assert entry.to_version_sequence == 2
    assert entry.summary.total_metrics_changed >= 1
    assert entry.summary.total_metrics_compared == entry.summary.total_metrics_changed
    assert entry.summary.has_material_change is True


@pytest.mark.anyio
async def test_get_restatement_ledger_raises_on_no_versions() -> None:
    repo = FakeEdgarStatementsRepository([])
    uow = FakeUnitOfWork(repo)
    uc = GetRestatementLedgerUseCase(uow=uow)

    req = GetRestatementLedgerRequest(
        cik="0000320193",
        statement_type=StatementType.INCOME_STATEMENT,
        fiscal_year=2024,
        fiscal_period=FiscalPeriod.FY,
    )

    with pytest.raises(EdgarIngestionError):
        await uc.execute(req)


@pytest.mark.anyio
async def test_get_restatement_ledger_raises_on_insufficient_normalized_versions() -> None:
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
    uc = GetRestatementLedgerUseCase(uow=uow)

    req = GetRestatementLedgerRequest(
        cik="0000320193",
        statement_type=StatementType.INCOME_STATEMENT,
        fiscal_year=2024,
        fiscal_period=FiscalPeriod.FY,
    )

    with pytest.raises(EdgarIngestionError):
        await uc.execute(req)


@pytest.mark.anyio
async def test_get_restatement_ledger_validates_request_fields() -> None:
    repo = FakeEdgarStatementsRepository([])
    uow = FakeUnitOfWork(repo)
    uc = GetRestatementLedgerUseCase(uow=uow)

    bad_cik = GetRestatementLedgerRequest(
        cik="  ",
        statement_type=StatementType.INCOME_STATEMENT,
        fiscal_year=2024,
        fiscal_period=FiscalPeriod.FY,
    )
    with pytest.raises(EdgarMappingError):
        await uc.execute(bad_cik)

    bad_year = GetRestatementLedgerRequest(
        cik="0000320193",
        statement_type=StatementType.INCOME_STATEMENT,
        fiscal_year=0,
        fiscal_period=FiscalPeriod.FY,
    )
    with pytest.raises(EdgarMappingError):
        await uc.execute(bad_year)
