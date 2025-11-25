# Copyright (c) Stacklion.
# SPDX-License-Identifier: MIT
"""Unit tests for EdgarPresenter."""

from __future__ import annotations

from datetime import date

from stacklion_api.adapters.presenters.edgar_presenter import EdgarPresenter
from stacklion_api.adapters.schemas.http.edgar_schemas import (
    EdgarFilingHTTP,
    EdgarStatementVersionListHTTP,
    EdgarStatementVersionSummaryHTTP,
)
from stacklion_api.adapters.schemas.http.envelopes import PaginatedEnvelope, SuccessEnvelope
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


def _make_filing_dto(accession_id: str, filing_date: date) -> EdgarFilingDTO:
    return EdgarFilingDTO(
        accession_id=accession_id,
        cik="0000000001",
        company_name="Test Co",
        filing_type=FilingType("10-K"),
        filing_date=filing_date,
        period_end_date=filing_date,
        is_amendment=False,
        amendment_sequence=None,
        primary_document="test.htm",
        accepted_at=None,
    )


def _make_statement_dto(
    accession_id: str, statement_date: date, version_sequence: int
) -> EdgarStatementVersionDTO:
    return EdgarStatementVersionDTO(
        accession_id=accession_id,
        cik="0000000001",
        company_name="Test Co",
        statement_type=StatementType.INCOME_STATEMENT,
        accounting_standard=AccountingStandard.US_GAAP,
        statement_date=statement_date,
        fiscal_year=statement_date.year,
        fiscal_period=FiscalPeriod.FY,
        currency="USD",
        is_restated=False,
        restatement_reason=None,
        version_source="EDGAR_METADATA_ONLY",
        version_sequence=version_sequence,
        filing_type=FilingType("10-K"),
        filing_date=statement_date,
        accepted_at=None,
    )


def test_present_filings_page_sorts_desc() -> None:
    """present_filings_page should sort filings by date DESC then accession_id DESC."""
    presenter = EdgarPresenter()
    older = _make_filing_dto("A", date(2024, 1, 1))
    newer = _make_filing_dto("B", date(2024, 2, 1))

    result = presenter.present_filings_page(
        dtos=[older, newer],
        page=1,
        page_size=10,
        total=2,
        trace_id="trace-1",
    )

    assert isinstance(result.body, PaginatedEnvelope)
    items = result.body.items
    assert isinstance(items[0], EdgarFilingHTTP)
    assert items[0].accession_id == "B"
    assert items[1].accession_id == "A"
    assert result.headers.get("X-Request-ID") == "trace-1"


def test_present_filing_detail_wraps_success_envelope() -> None:
    """present_filing_detail should wrap filing in SuccessEnvelope."""
    presenter = EdgarPresenter()
    dto = _make_filing_dto("A", date(2024, 1, 1))

    result = presenter.present_filing_detail(dto=dto, trace_id="req-1")
    assert isinstance(result.body, SuccessEnvelope)
    assert isinstance(result.body.data, EdgarFilingHTTP)
    assert result.body.data.accession_id == "A"
    assert result.headers.get("X-Request-ID") == "req-1"
    assert "ETag" in result.headers


def test_present_statement_versions_page_sorts_desc() -> None:
    """present_statement_versions_page should sort by statement_date DESC, version_sequence DESC."""
    presenter = EdgarPresenter()

    older_v1 = _make_statement_dto("A", date(2024, 1, 1), 1)
    newer_v1 = _make_statement_dto("B", date(2024, 2, 1), 1)
    newer_v2 = _make_statement_dto("B", date(2024, 2, 1), 2)

    result = presenter.present_statement_versions_page(
        dtos=[older_v1, newer_v1, newer_v2],
        page=1,
        page_size=10,
        total=3,
        trace_id="trace-2",
    )

    assert isinstance(result.body, PaginatedEnvelope)
    items = result.body.items
    assert isinstance(items[0], EdgarStatementVersionSummaryHTTP)
    # Expect B v2, B v1, A v1
    assert items[0].accession_id == "B"
    assert items[0].version_sequence == 2
    assert items[1].accession_id == "B"
    assert items[1].version_sequence == 1
    assert items[2].accession_id == "A"
    assert items[2].version_sequence == 1


def test_present_statement_versions_for_filing_constructs_container() -> None:
    """present_statement_versions_for_filing should build EdgarStatementVersionListHTTP."""
    presenter = EdgarPresenter()
    filing = _make_filing_dto("A", date(2024, 1, 1))
    v1 = _make_statement_dto("A", date(2024, 1, 1), 1)

    result = presenter.present_statement_versions_for_filing(
        filing=filing,
        versions=[v1],
        include_normalized=True,
        trace_id="trace-3",
    )

    assert isinstance(result.body, SuccessEnvelope)
    container = result.body.data
    assert isinstance(container, EdgarStatementVersionListHTTP)
    assert container.filing.accession_id == "A"
    assert len(container.items) == 1
    assert container.items[0].normalized_payload is None
    assert result.headers.get("X-Request-ID") == "trace-3"
