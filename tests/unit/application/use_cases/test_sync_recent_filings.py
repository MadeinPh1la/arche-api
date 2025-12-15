# tests/unit/application/use_cases/test_sync_recent_filings_use_case.py
from __future__ import annotations

from collections.abc import Sequence
from datetime import UTC, date, datetime
from types import TracebackType
from typing import Any

import pytest

from arche_api.adapters.repositories.edgar_filings_repository import (
    EdgarFilingsRepository,
)
from arche_api.adapters.repositories.edgar_statements_repository import (
    EdgarStatementsRepository,
)
from arche_api.application.uow import UnitOfWork
from arche_api.application.use_cases.external_apis.edgar.sync_recent_filings import (
    SyncRecentFilingsRequest,
    SyncRecentFilingsUseCase,
)
from arche_api.domain.entities.edgar_company import EdgarCompanyIdentity
from arche_api.domain.entities.edgar_filing import EdgarFiling
from arche_api.domain.entities.edgar_statement_version import EdgarStatementVersion
from arche_api.domain.enums.edgar import (
    AccountingStandard,
    FilingType,
    FiscalPeriod,
    StatementType,
)
from arche_api.domain.interfaces.gateways.edgar_ingestion_gateway import (
    EdgarIngestionGateway,
)


class FakeEdgarGateway(EdgarIngestionGateway):
    def __init__(self) -> None:
        self.company = EdgarCompanyIdentity(
            cik="0000123456",
            ticker="TEST",
            legal_name="Test Company Inc.",
            exchange=None,
            country=None,
        )
        self.filings: list[EdgarFiling] = [
            EdgarFiling(
                accession_id="0000123456-24-000001",
                company=self.company,
                filing_type=FilingType.FORM_10K,
                filing_date=date(2024, 1, 31),
                period_end_date=date(2023, 12, 31),
                accepted_at=datetime(2024, 1, 31, 12, 0, tzinfo=UTC),
                is_amendment=False,
                amendment_sequence=None,
                primary_document="test10k.htm",
                data_source="EDGAR",
            ),
            EdgarFiling(
                accession_id="0000123456-24-000002",
                company=self.company,
                filing_type=FilingType.FORM_10Q,
                filing_date=date(2024, 4, 30),
                period_end_date=date(2024, 3, 31),
                accepted_at=datetime(2024, 4, 30, 12, 0, tzinfo=UTC),
                is_amendment=False,
                amendment_sequence=None,
                primary_document="test10q.htm",
                data_source="EDGAR",
            ),
        ]

    async def fetch_company_identity(self, cik: str) -> EdgarCompanyIdentity:
        return self.company

    async def fetch_filings_for_company(
        self,
        company: EdgarCompanyIdentity,
        filing_types: Sequence[FilingType],
        from_date: date,
        to_date: date,
        include_amendments: bool = True,
        max_results: int | None = None,
    ) -> Sequence[EdgarFiling]:
        return list(self.filings)

    async def fetch_statement_versions_for_filing(
        self,
        filing: EdgarFiling,
        statement_types: Sequence[StatementType],
    ) -> Sequence[EdgarStatementVersion]:
        versions: list[EdgarStatementVersion] = []
        statement_date = filing.period_end_date or filing.filing_date
        fiscal_year = statement_date.year

        for idx, st_type in enumerate(statement_types, start=1):
            versions.append(
                EdgarStatementVersion(
                    company=filing.company,
                    filing=filing,
                    statement_type=st_type,
                    accounting_standard=AccountingStandard.US_GAAP,
                    statement_date=statement_date,
                    fiscal_year=fiscal_year,
                    fiscal_period=FiscalPeriod.FY,
                    currency="USD",
                    is_restated=False,
                    restatement_reason=None,
                    version_source="TEST",
                    version_sequence=idx,
                    accession_id=filing.accession_id,
                    filing_date=filing.filing_date,
                )
            )
        return versions


class FakeFilingsRepo:
    def __init__(self, existing_accessions: set[str] | None = None) -> None:
        self.existing_accessions = existing_accessions or set()
        self.upsert_calls: list[list[EdgarFiling]] = []

    async def list_filings_for_company(
        self,
        company: EdgarCompanyIdentity,
        from_date: date | None = None,
        to_date: date | None = None,
        filing_types: Sequence[FilingType] | None = None,
        limit: int | None = None,
    ) -> Sequence[Any]:
        # Return simple rows with an `accession` attribute.
        class Row:
            def __init__(self, accession: str) -> None:
                self.accession = accession

        return [Row(a) for a in self.existing_accessions]

    async def upsert_filings(self, filings: Sequence[EdgarFiling]) -> int:
        self.upsert_calls.append(list(filings))
        for f in filings:
            self.existing_accessions.add(f.accession_id)
        return len(filings)


class FakeStatementsRepo:
    def __init__(self) -> None:
        self.upsert_calls: list[list[EdgarStatementVersion]] = []

    async def upsert_statement_versions(
        self,
        versions: Sequence[EdgarStatementVersion],
    ) -> None:
        self.upsert_calls.append(list(versions))


class FakeUnitOfWork(UnitOfWork):
    def __init__(self, existing_accessions: set[str] | None = None) -> None:
        self.filings_repo = FakeFilingsRepo(existing_accessions)
        self.statements_repo = FakeStatementsRepo()
        self._committed = False
        self._rolled_back = False

    async def __aenter__(self) -> FakeUnitOfWork:
        return self

    async def __aexit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        tb: TracebackType | None,
    ) -> bool | None:
        if exc_type is not None and not self._rolled_back:
            await self.rollback()
        return None

    async def commit(self) -> None:
        self._committed = True

    async def rollback(self) -> None:
        self._rolled_back = True

    def get_repository(self, repo_type: type[Any]) -> Any:
        if repo_type is EdgarFilingsRepository:
            return self.filings_repo
        if repo_type is EdgarStatementsRepository:
            return self.statements_repo
        raise KeyError(f"Unknown repository type requested: {repo_type!r}")

    @property
    def committed(self) -> bool:
        return self._committed

    @property
    def rolled_back(self) -> bool:
        return self._rolled_back


@pytest.mark.anyio
async def test_sync_recent_filings_ingests_only_new() -> None:
    gateway = FakeEdgarGateway()
    existing = {"0000123456-24-000001"}
    uow = FakeUnitOfWork(existing_accessions=existing)

    uc = SyncRecentFilingsUseCase(gateway=gateway, uow=uow)

    req = SyncRecentFilingsRequest(
        cik="0000123456",
        filing_types=[FilingType.FORM_10K, FilingType.FORM_10Q],
        from_date=None,
        to_date=None,
        include_amendments=True,
        statement_types=[StatementType.INCOME_STATEMENT],
    )

    count = await uc.execute(req)

    # One new filing, one statement type -> 1 version
    assert count == 1
    assert len(uow.filings_repo.upsert_calls) == 1
    assert len(uow.filings_repo.upsert_calls[0]) == 1
    assert len(uow.statements_repo.upsert_calls) == 1
    assert uow.committed is True
    assert uow.rolled_back is False


@pytest.mark.anyio
async def test_sync_recent_filings_idempotent_when_all_exist() -> None:
    gateway = FakeEdgarGateway()
    existing = {f.accession_id for f in gateway.filings}
    uow = FakeUnitOfWork(existing_accessions=existing)

    uc = SyncRecentFilingsUseCase(gateway=gateway, uow=uow)

    req = SyncRecentFilingsRequest(
        cik="0000123456",
        filing_types=[FilingType.FORM_10K, FilingType.FORM_10Q],
        from_date=None,
        to_date=None,
        include_amendments=True,
        statement_types=[StatementType.INCOME_STATEMENT],
    )

    count = await uc.execute(req)

    assert count == 0
    assert uow.filings_repo.upsert_calls == []
    assert uow.statements_repo.upsert_calls == []
    assert uow.committed is True
    assert uow.rolled_back is False
