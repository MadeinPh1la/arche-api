# tests/unit/application/use_cases/external_apis/edgar/test_process_xbrl_for_filing.py
# Copyright (c)
# SPDX-License-Identifier: MIT

from __future__ import annotations

from collections.abc import Sequence
from datetime import date
from decimal import Decimal
from typing import Any

import pytest

from arche_api.application.use_cases.external_apis.edgar.process_xbrl_for_filing import (
    ProcessXBRLForFilingRequest,
    ProcessXBRLForFilingUseCase,
)
from arche_api.domain.entities.canonical_statement_payload import CanonicalStatementPayload
from arche_api.domain.entities.edgar_company import EdgarCompanyIdentity
from arche_api.domain.entities.edgar_filing import EdgarFiling
from arche_api.domain.entities.edgar_normalized_fact import EdgarNormalizedFact
from arche_api.domain.entities.edgar_statement_version import EdgarStatementVersion
from arche_api.domain.entities.xbrl_document import (
    XBRLContext,
    XBRLDocument,
    XBRLFact,
    XBRLPeriod,
    XBRLUnit,
)
from arche_api.domain.enums.canonical_statement_metric import CanonicalStatementMetric
from arche_api.domain.enums.edgar import (
    AccountingStandard,
    FilingType,
    FiscalPeriod,
    StatementType,
)
from arche_api.domain.exceptions.edgar import EdgarIngestionError, EdgarMappingError
from arche_api.domain.services.edgar_normalization import (
    NormalizationContext,
    NormalizationResult,
)

# ---------------------------------------------------------------------------
# Fakes
# ---------------------------------------------------------------------------


class _FakeIngestionGateway:
    def __init__(self, payload: bytes) -> None:
        self._payload = payload
        self.calls: list[tuple[str, str]] = []

    async def fetch_xbrl_for_filing(self, *, cik: str, accession_id: str) -> bytes:
        self.calls.append((cik, accession_id))
        return self._payload


class _FakeXBRLParserGateway:
    def __init__(self, document: XBRLDocument) -> None:
        self._document = document
        self.calls: list[tuple[str, bytes | str]] = []

    async def parse_xbrl(self, *, accession_id: str, content: bytes | str) -> XBRLDocument:
        self.calls.append((accession_id, content))
        return self._document


class _FakeStatementsRepo:
    def __init__(self, versions: Sequence[EdgarStatementVersion]) -> None:
        self._versions = list(versions)
        self.upserted: Sequence[EdgarStatementVersion] | None = None

    async def list_statement_versions_for_company(
        self,
        *,
        cik: str,
        statement_type: Any = None,
        fiscal_year: int = 0,
        fiscal_period: Any = None,
    ) -> Sequence[EdgarStatementVersion]:
        # For E10-A test purposes we ignore filters and return all seeded versions.
        return list(self._versions)

    async def upsert_statement_versions(
        self,
        versions: Sequence[EdgarStatementVersion],
    ) -> None:
        self.upserted = list(versions)


class _FakeFactsRepo:
    def __init__(self) -> None:
        self.replacements: list[tuple[Any, list[EdgarNormalizedFact]]] = []

    async def replace_facts_for_statement(
        self,
        identity: Any,
        facts: Sequence[EdgarNormalizedFact],
    ) -> None:
        self.replacements.append((identity, list(facts)))


class _FakeUoW:
    def __init__(self, statements_repo: _FakeStatementsRepo, facts_repo: _FakeFactsRepo) -> None:
        self._repo_map = {
            _FakeStatementsRepo: statements_repo,
            _FakeFactsRepo: facts_repo,
        }
        self.committed = False

    async def __aenter__(self) -> _FakeUoW:
        return self

    async def __aexit__(self, exc_type, exc, tb) -> None:  # type: ignore[override]
        return None

    def get_repository(self, repo_type: type) -> Any:
        return self._repo_map[repo_type]

    async def commit(self) -> None:
        self.committed = True


class _FakeNormalizer:
    """Deterministic normalizer used to avoid complexity of real engine."""

    def normalize(self, context: NormalizationContext) -> NormalizationResult:
        payload = CanonicalStatementPayload(
            cik=context.cik,
            statement_type=context.statement_type,
            accounting_standard=context.accounting_standard,
            statement_date=context.statement_date,
            fiscal_year=context.fiscal_year,
            fiscal_period=context.fiscal_period,
            currency=context.currency,
            unit_multiplier=0,
            core_metrics={CanonicalStatementMetric.REVENUE: Decimal("100")},
            extra_metrics={},
            dimensions={"consolidation": "CONSOLIDATED"},
            source_accession_id=context.accession_id,
            source_taxonomy=context.taxonomy,
            source_version_sequence=context.version_sequence,
        )
        return NormalizationResult(
            payload=payload,
            payload_version="v_test",
            metric_records={},
            warnings=(),
        )


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _build_xbrl_document() -> XBRLDocument:
    period = XBRLPeriod(
        is_instant=False,
        instant_date=None,
        start_date=date(2024, 1, 1),
        end_date=date(2024, 12, 31),
    )
    ctx = XBRLContext(
        id="C1",
        entity_identifier="0000123456",
        period=period,
        dimensions=(),
    )
    unit = XBRLUnit(id="U1", measure="iso4217:USD")
    fact = XBRLFact(
        id="f1",
        concept_qname="us-gaap:Revenues",
        context_ref="C1",
        unit_ref="U1",
        raw_value="100",
        decimals=0,
        precision=None,
        is_nil=False,
        footnote_refs=(),
    )
    return XBRLDocument(
        accession_id="0000123456-24-000001",
        contexts={"C1": ctx},
        units={"U1": unit},
        facts=(fact,),
    )


def _build_statement_version(accession_id: str) -> EdgarStatementVersion:
    company = EdgarCompanyIdentity(
        cik="0000123456",
        ticker="TEST",
        legal_name="Test Corp",
        exchange=None,
        country=None,
    )
    filing = EdgarFiling(
        accession_id=accession_id,
        company=company,
        filing_type=FilingType.FORM_10_K,
        filing_date=date(2025, 2, 1),
        period_end_date=date(2024, 12, 31),
        accepted_at=None,
        is_amendment=False,
        amendment_sequence=None,
        primary_document="doc.xml",
        data_source="EDGAR",
    )
    return EdgarStatementVersion(
        company=company,
        filing=filing,
        statement_type=StatementType.INCOME_STATEMENT,
        accounting_standard=AccountingStandard.US_GAAP,
        statement_date=date(2024, 12, 31),
        fiscal_year=2024,
        fiscal_period=FiscalPeriod.FY,
        currency="USD",
        is_restated=False,
        restatement_reason=None,
        version_source="EDGAR_METADATA_ONLY",
        version_sequence=1,
        accession_id=accession_id,
        filing_date=filing.filing_date,
    )


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_process_xbrl_for_filing_happy_path_normalizes_and_persists() -> None:
    accession_id = "0000123456-24-000001"
    xbrl_bytes = b"<xbrli:xbrl/>"  # content doesn't matter; fake parser returns a prebuilt document
    doc = _build_xbrl_document()
    statement = _build_statement_version(accession_id)

    ingestion_gateway = _FakeIngestionGateway(payload=xbrl_bytes)
    parser_gateway = _FakeXBRLParserGateway(document=doc)
    statements_repo = _FakeStatementsRepo(versions=[statement])
    facts_repo = _FakeFactsRepo()
    uow = _FakeUoW(statements_repo=statements_repo, facts_repo=facts_repo)

    use_case = ProcessXBRLForFilingUseCase(
        uow=uow,
        ingestion_gateway=ingestion_gateway,
        xbrl_parser_gateway=parser_gateway,
        statements_repo_type=_FakeStatementsRepo,
        facts_repo_type=_FakeFactsRepo,
    )
    # Inject fake normalizer to avoid dependency on the full engine.
    use_case._normalizer = _FakeNormalizer()  # type: ignore[attr-defined]

    req = ProcessXBRLForFilingRequest(
        cik="0000123456",
        accession_id=accession_id,
        statement_types=[StatementType.INCOME_STATEMENT],
    )

    result = await use_case.execute(req)

    assert result.cik == "0000123456"
    assert result.accession_id == accession_id
    assert result.statement_types_processed == (StatementType.INCOME_STATEMENT,)
    # One canonical metric (REVENUE) → one fact.
    assert result.facts_persisted == 1

    # Statements repo received updated version.
    assert statements_repo.upserted is not None
    assert len(statements_repo.upserted) == 1
    updated = statements_repo.upserted[0]
    assert updated.normalized_payload is not None
    assert updated.version_source == "EDGAR_XBRL_NORMALIZED"

    # Facts repo has a replacement call with at least one fact.
    assert len(facts_repo.replacements) == 1
    identity, facts = facts_repo.replacements[0]
    assert facts
    assert isinstance(facts[0], EdgarNormalizedFact)
    assert facts[0].metric_code == CanonicalStatementMetric.REVENUE.value
    assert facts[0].value == Decimal("100")


@pytest.mark.asyncio
async def test_process_xbrl_for_filing_raises_on_empty_cik() -> None:
    use_case = ProcessXBRLForFilingUseCase(
        uow=_FakeUoW(_FakeStatementsRepo(versions=[]), _FakeFactsRepo()),
        ingestion_gateway=_FakeIngestionGateway(payload=b""),
        xbrl_parser_gateway=_FakeXBRLParserGateway(document=_build_xbrl_document()),
        statements_repo_type=_FakeStatementsRepo,
        facts_repo_type=_FakeFactsRepo,
    )

    req = ProcessXBRLForFilingRequest(
        cik="   ",
        accession_id="0000123456-24-000001",
        statement_types=[StatementType.INCOME_STATEMENT],
    )

    with pytest.raises(EdgarMappingError):
        await use_case.execute(req)


@pytest.mark.asyncio
async def test_process_xbrl_for_filing_raises_on_empty_accession() -> None:
    use_case = ProcessXBRLForFilingUseCase(
        uow=_FakeUoW(_FakeStatementsRepo(versions=[]), _FakeFactsRepo()),
        ingestion_gateway=_FakeIngestionGateway(payload=b""),
        xbrl_parser_gateway=_FakeXBRLParserGateway(document=_build_xbrl_document()),
        statements_repo_type=_FakeStatementsRepo,
        facts_repo_type=_FakeFactsRepo,
    )

    req = ProcessXBRLForFilingRequest(
        cik="0000123456",
        accession_id="   ",
        statement_types=[StatementType.INCOME_STATEMENT],
    )

    with pytest.raises(EdgarMappingError):
        await use_case.execute(req)


@pytest.mark.asyncio
async def test_process_xbrl_for_filing_raises_when_no_versions_found() -> None:
    accession_id = "0000123456-24-000001"
    ingestion_gateway = _FakeIngestionGateway(payload=b"")
    parser_gateway = _FakeXBRLParserGateway(document=_build_xbrl_document())
    statements_repo = _FakeStatementsRepo(versions=[])
    facts_repo = _FakeFactsRepo()
    uow = _FakeUoW(statements_repo=statements_repo, facts_repo=facts_repo)

    use_case = ProcessXBRLForFilingUseCase(
        uow=uow,
        ingestion_gateway=ingestion_gateway,
        xbrl_parser_gateway=parser_gateway,
        statements_repo_type=_FakeStatementsRepo,
        facts_repo_type=_FakeFactsRepo,
    )
    use_case._normalizer = _FakeNormalizer()  # type: ignore[attr-defined]

    req = ProcessXBRLForFilingRequest(
        cik="0000123456",
        accession_id=accession_id,
        statement_types=[StatementType.INCOME_STATEMENT],
    )

    with pytest.raises(EdgarIngestionError):
        await use_case.execute(req)
