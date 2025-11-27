from __future__ import annotations

from collections.abc import Sequence
from datetime import UTC, date, datetime
from types import TracebackType
from typing import Any

import pytest

from stacklion_api.adapters.repositories.edgar_filings_repository import (
    EdgarFilingsRepository,
)
from stacklion_api.adapters.repositories.edgar_statements_repository import (
    EdgarStatementsRepository,
)
from stacklion_api.application.uow import UnitOfWork
from stacklion_api.application.use_cases.external_apis.edgar.ingest_edgar_filing import (
    IngestEdgarFilingRequest,
    IngestEdgarFilingUseCase,
)
from stacklion_api.domain.entities.edgar_company import EdgarCompanyIdentity
from stacklion_api.domain.entities.edgar_filing import EdgarFiling
from stacklion_api.domain.entities.edgar_statement_version import EdgarStatementVersion
from stacklion_api.domain.enums.edgar import (
    AccountingStandard,
    FilingType,
    FiscalPeriod,
    StatementType,
)
from stacklion_api.domain.exceptions.edgar import EdgarIngestionError
from stacklion_api.domain.interfaces.gateways.edgar_ingestion_gateway import (
    EdgarIngestionGateway,
)


class FakeEdgarIngestionGateway(EdgarIngestionGateway):
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
    def __init__(self) -> None:
        self.upsert_calls: list[list[EdgarFiling]] = []

    async def upsert_filings(self, filings: Sequence[EdgarFiling]) -> int:
        self.upsert_calls.append(list(filings))
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
    def __init__(self) -> None:
        self.filings_repo = FakeFilingsRepo()
        self.statements_repo = FakeStatementsRepo()
        self._committed = False
        self._rolled_back = False
        self._entered = False

    async def __aenter__(self) -> FakeUnitOfWork:
        self._entered = True
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

    @property
    def entered(self) -> bool:
        return self._entered


@pytest.mark.anyio
async def test_ingest_edgar_filing_happy_path() -> None:
    gateway = FakeEdgarIngestionGateway()
    uow = FakeUnitOfWork()

    uc = IngestEdgarFilingUseCase(gateway=gateway, uow=uow)

    req = IngestEdgarFilingRequest(
        cik="0000123456",
        accession_id="0000123456-24-000001",
        statement_types=[StatementType.INCOME_STATEMENT, StatementType.BALANCE_SHEET],
    )

    count = await uc.execute(req)

    assert count == 2
    assert len(uow.filings_repo.upsert_calls) == 1
    assert len(uow.statements_repo.upsert_calls) == 1
    assert uow.committed is True
    assert uow.rolled_back is False
    assert uow.entered is True


@pytest.mark.anyio
async def test_ingest_edgar_filing_not_found_raises_and_does_not_touch_uow() -> None:
    """If the filing is not found, the UoW is never entered."""
    gateway = FakeEdgarIngestionGateway()
    uow = FakeUnitOfWork()
    uc = IngestEdgarFilingUseCase(gateway=gateway, uow=uow)

    req = IngestEdgarFilingRequest(
        cik="0000123456",
        accession_id="0000123456-24-999999",
        statement_types=[StatementType.INCOME_STATEMENT],
    )

    with pytest.raises(EdgarIngestionError):
        await uc.execute(req)

    # No transaction scope was opened, so neither commit nor rollback should run.
    assert uow.entered is False
    assert uow.committed is False
    assert uow.rolled_back is False
    assert uow.filings_repo.upsert_calls == []
    assert uow.statements_repo.upsert_calls == []
