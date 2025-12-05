import datetime

import pytest

from stacklion_api.application.uow import UnitOfWork
from stacklion_api.application.use_cases.statements.normalize_xbrl_statement import (
    NormalizeXBRLStatementRequest,
    NormalizeXBRLStatementUseCase,
)
from stacklion_api.domain.entities.edgar_company import EdgarCompanyIdentity
from stacklion_api.domain.entities.edgar_filing import EdgarFiling
from stacklion_api.domain.entities.edgar_statement_version import EdgarStatementVersion
from stacklion_api.domain.entities.xbrl_document import (
    XBRLContext,
    XBRLDocument,
    XBRLFact,
    XBRLPeriod,
    XBRLUnit,
)
from stacklion_api.domain.enums.edgar import (
    AccountingStandard,
    FilingType,
    FiscalPeriod,
    StatementType,
)


class _FakeTx:
    def __init__(self, repo: object) -> None:
        self._repo = repo

    async def __aenter__(self) -> "_FakeTx":
        return self

    async def __aexit__(self, exc_type, exc, tb) -> None:  # type: ignore[override]
        return None

    def get_repository(self, repo_type: object) -> object:
        return self._repo

    async def commit(self) -> None:
        return None


class _FakeUoW(UnitOfWork):  # type: ignore[misc]
    def __init__(self, repo: object) -> None:
        self._repo = repo

    async def __aenter__(self) -> _FakeTx:  # type: ignore[override]
        return _FakeTx(self._repo)

    async def __aexit__(self, exc_type, exc, tb) -> None:  # type: ignore[override]
        return None


class _FakeStatementsRepository:
    def __init__(self, version: EdgarStatementVersion) -> None:
        self._version = version
        self.upserted: list[EdgarStatementVersion] = []

    async def list_statement_versions_for_company(
        self,
        *,
        cik: str,
        statement_type: StatementType,
        fiscal_year: int,
        fiscal_period: FiscalPeriod,
    ) -> list[EdgarStatementVersion]:
        return [self._version]

    async def upsert_statement_versions(self, versions: list[EdgarStatementVersion]) -> None:
        self.upserted.extend(versions)


@pytest.mark.asyncio
async def test_normalize_xbrl_statement_use_case_updates_version() -> None:
    today = datetime.date(2024, 12, 31)

    company = EdgarCompanyIdentity(
        cik="0000000000",
        ticker="FAKE",
        legal_name="Fake Corp",
        exchange=None,
        country=None,
    )

    filing = EdgarFiling(
        accession_id="0000000000-24-000001",
        company=company,
        filing_type=FilingType.FORM_10_K,
        filing_date=today,
        period_end_date=today,
        accepted_at=None,
        is_amendment=False,
        amendment_sequence=None,
        primary_document=None,
        data_source="TEST",
    )

    base_version = EdgarStatementVersion(
        company=company,
        filing=filing,
        statement_type=StatementType.INCOME_STATEMENT,
        accounting_standard=AccountingStandard.US_GAAP,
        statement_date=today,
        fiscal_year=today.year,
        fiscal_period=FiscalPeriod.FY,
        currency="USD",
        is_restated=False,
        restatement_reason=None,
        version_source="EDGAR_METADATA_ONLY",
        version_sequence=1,
        accession_id=filing.accession_id,
        filing_date=filing.filing_date,
        normalized_payload=None,
        normalized_payload_version=None,
    )

    period = XBRLPeriod(
        is_instant=False,
        instant_date=None,
        start_date=datetime.date(2024, 1, 1),
        end_date=today,
    )
    ctx = XBRLContext(
        id="C1",
        entity_identifier="0000000000",
        period=period,
        dimensions=(),
    )
    unit = XBRLUnit(id="U1", measure="ISO4217:USD")
    fact = XBRLFact(
        id=None,
        concept_qname="us-gaap:Revenues",
        context_ref="C1",
        unit_ref="U1",
        raw_value="1000",
        decimals=0,
        precision=None,
        is_nil=False,
        footnote_refs=(),
    )
    document = XBRLDocument(
        accession_id=filing.accession_id,
        contexts={"C1": ctx},
        units={"U1": unit},
        facts=(fact,),
    )

    repo = _FakeStatementsRepository(version=base_version)
    uow = _FakeUoW(repo=repo)
    uc = NormalizeXBRLStatementUseCase(uow=uow)

    req = NormalizeXBRLStatementRequest(
        cik=company.cik,
        statement_type=StatementType.INCOME_STATEMENT,
        fiscal_year=base_version.fiscal_year,
        fiscal_period=base_version.fiscal_period,
        accession_id=base_version.accession_id,
        version_sequence=base_version.version_sequence,
        xbrl_document=document,
    )

    await uc.execute(req)

    assert len(repo.upserted) == 1
    updated = repo.upserted[0]
    assert updated.normalized_payload is not None
    assert updated.version_source == "EDGAR_XBRL_NORMALIZED"
