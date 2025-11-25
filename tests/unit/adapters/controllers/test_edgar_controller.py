# Copyright (c) Stacklion.
# SPDX-License-Identifier: MIT
"""Unit tests for EdgarController."""

from __future__ import annotations

from datetime import date

import pytest

from stacklion_api.adapters.controllers.edgar_controller import EdgarController
from stacklion_api.application.schemas.dto.edgar import (
    EdgarFilingDTO,
    EdgarStatementVersionDTO,
)
from stacklion_api.domain.enums.edgar import (
    AccountingStandard,
    FilingType,
    FiscalPeriod,
    StatementType,
)


class _FakeListFilingsUC:
    def __init__(self) -> None:
        self.called_with: dict[str, object] | None = None

    async def execute(
        self,
        *,
        cik: str,
        filing_types,
        from_date,
        to_date,
        include_amendments,
        page,
        page_size,
    ):
        self.called_with = {
            "cik": cik,
            "filing_types": filing_types,
            "from_date": from_date,
            "to_date": to_date,
            "include_amendments": include_amendments,
            "page": page,
            "page_size": page_size,
        }
        dto = EdgarFilingDTO(
            accession_id="A",
            cik=cik,
            company_name="Test Co",
            filing_type=FilingType("10-K"),
            filing_date=date(2024, 1, 1),
            period_end_date=date(2023, 12, 31),
            is_amendment=False,
            amendment_sequence=None,
            primary_document="test.htm",
            accepted_at=None,
        )
        return [dto], 1


class _FakeGetFilingUC:
    def __init__(self) -> None:
        self.called_with: dict[str, str] | None = None

    async def execute(self, *, cik: str, accession_id: str) -> EdgarFilingDTO:  # type: ignore[override]
        self.called_with = {"cik": cik, "accession_id": accession_id}
        return EdgarFilingDTO(
            accession_id=accession_id,
            cik=cik,
            company_name="Test Co",
            filing_type=FilingType("10-K"),
            filing_date=date(2024, 1, 1),
            period_end_date=date(2023, 12, 31),
            is_amendment=False,
            amendment_sequence=None,
            primary_document="test.htm",
            accepted_at=None,
        )


class _FakeListStatementsUC:
    def __init__(self) -> None:
        self.called_with: dict[str, object] | None = None

    async def execute(
        self,
        *,
        cik: str,
        statement_type,
        from_date,
        to_date,
        include_restated,
        page,
        page_size,
    ):
        self.called_with = {
            "cik": cik,
            "statement_type": statement_type,
            "from_date": from_date,
            "to_date": to_date,
            "include_restated": include_restated,
            "page": page,
            "page_size": page_size,
        }
        dto = EdgarStatementVersionDTO(
            accession_id="A",
            cik=cik,
            company_name="Test Co",
            statement_type=StatementType.INCOME_STATEMENT,
            accounting_standard=AccountingStandard.US_GAAP,
            statement_date=date(2023, 12, 31),
            fiscal_year=2023,
            fiscal_period=FiscalPeriod.FY,
            currency="USD",
            is_restated=False,
            restatement_reason=None,
            version_source="EDGAR_METADATA_ONLY",
            version_sequence=1,
            filing_type=FilingType("10-K"),
            filing_date=date(2024, 1, 1),
            accepted_at=None,
        )
        return [dto], 1


class _FakeGetFilingStatementsUC:
    def __init__(self) -> None:
        self.called_with: dict[str, object] | None = None

    async def execute(
        self,
        *,
        cik: str,
        accession_id: str,
        statement_type,
        include_restated: bool,
        include_normalized: bool,
    ):
        self.called_with = {
            "cik": cik,
            "accession_id": accession_id,
            "statement_type": statement_type,
            "include_restated": include_restated,
            "include_normalized": include_normalized,
        }
        filing = EdgarFilingDTO(
            accession_id=accession_id,
            cik=cik,
            company_name="Test Co",
            filing_type=FilingType("10-K"),
            filing_date=date(2024, 1, 1),
            period_end_date=date(2023, 12, 31),
            is_amendment=False,
            amendment_sequence=None,
            primary_document="test.htm",
            accepted_at=None,
        )
        version = EdgarStatementVersionDTO(
            accession_id=accession_id,
            cik=cik,
            company_name="Test Co",
            statement_type=StatementType.INCOME_STATEMENT,
            accounting_standard=AccountingStandard.US_GAAP,
            statement_date=date(2023, 12, 31),
            fiscal_year=2023,
            fiscal_period=FiscalPeriod.FY,
            currency="USD",
            is_restated=False,
            restatement_reason=None,
            version_source="EDGAR_METADATA_ONLY",
            version_sequence=1,
            filing_type=FilingType("10-K"),
            filing_date=date(2024, 1, 1),
            accepted_at=None,
        )
        return filing, [version]


@pytest.mark.anyio
async def test_list_filings_delegates_to_use_case() -> None:
    """EdgarController.list_filings should delegate to ListFilingsUseCase."""
    uc = _FakeListFilingsUC()
    controller = EdgarController(
        list_filings_uc=uc,
        get_filing_uc=_FakeGetFilingUC(),
        list_statements_uc=_FakeListStatementsUC(),
        get_filing_statements_uc=_FakeGetFilingStatementsUC(),
    )

    filings, total = await controller.list_filings(
        cik=" 0000000001 ",
        filing_types=[FilingType("10-K")],
        from_date=date(2023, 1, 1),
        to_date=date(2024, 1, 1),
        include_amendments=True,
        page=1,
        page_size=10,
    )

    assert total == 1
    assert filings[0].accession_id == "A"
    assert uc.called_with is not None
    assert uc.called_with["cik"] == "0000000001"


@pytest.mark.anyio
async def test_get_filing_delegates_to_use_case() -> None:
    """EdgarController.get_filing should delegate to GetFilingUseCase."""
    get_uc = _FakeGetFilingUC()
    controller = EdgarController(
        list_filings_uc=_FakeListFilingsUC(),
        get_filing_uc=get_uc,
        list_statements_uc=_FakeListStatementsUC(),
        get_filing_statements_uc=_FakeGetFilingStatementsUC(),
    )

    dto = await controller.get_filing(cik=" 0000000001 ", accession_id=" A ")
    assert dto.accession_id == "A"
    assert get_uc.called_with is not None
    assert get_uc.called_with["cik"] == "0000000001"
    assert get_uc.called_with["accession_id"] == "A"


@pytest.mark.anyio
async def test_list_statements_delegates_to_use_case() -> None:
    """EdgarController.list_statements should delegate to ListStatementVersionsUseCase."""
    list_uc = _FakeListStatementsUC()
    controller = EdgarController(
        list_filings_uc=_FakeListFilingsUC(),
        get_filing_uc=_FakeGetFilingUC(),
        list_statements_uc=list_uc,
        get_filing_statements_uc=_FakeGetFilingStatementsUC(),
    )

    versions, total = await controller.list_statements(
        cik="0000000001",
        statement_type=StatementType.INCOME_STATEMENT,
        from_date=None,
        to_date=None,
        include_restated=False,
        page=2,
        page_size=25,
    )

    assert total == 1
    assert versions[0].statement_type == StatementType.INCOME_STATEMENT
    assert list_uc.called_with is not None
    assert list_uc.called_with["page"] == 2
    assert list_uc.called_with["page_size"] == 25


@pytest.mark.anyio
async def test_get_statement_versions_for_filing_delegates_to_use_case() -> None:
    """EdgarController.get_statement_versions_for_filing should delegate to its use-case."""
    get_uc = _FakeGetFilingStatementsUC()
    controller = EdgarController(
        list_filings_uc=_FakeListFilingsUC(),
        get_filing_uc=_FakeGetFilingUC(),
        list_statements_uc=_FakeListStatementsUC(),
        get_filing_statements_uc=get_uc,
    )

    filing, versions = await controller.get_statement_versions_for_filing(
        cik=" 0000000001 ",
        accession_id=" A ",
        statement_type=StatementType.INCOME_STATEMENT,
        include_restated=True,
        include_normalized=True,
    )

    assert filing.accession_id == "A"
    assert versions
    assert get_uc.called_with is not None
    assert get_uc.called_with["cik"] == "0000000001"
    assert get_uc.called_with["accession_id"] == "A"
    assert get_uc.called_with["statement_type"] == StatementType.INCOME_STATEMENT
    assert get_uc.called_with["include_restated"] is True
    assert get_uc.called_with["include_normalized"] is True
