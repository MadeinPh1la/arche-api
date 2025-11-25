from __future__ import annotations

from datetime import date, datetime

import pytest

from stacklion_api.domain.entities.edgar_company import EdgarCompanyIdentity
from stacklion_api.domain.entities.edgar_filing import EdgarFiling
from stacklion_api.domain.enums.edgar import FilingType
from stacklion_api.domain.exceptions.edgar import EdgarMappingError


def _make_company() -> EdgarCompanyIdentity:
    return EdgarCompanyIdentity(
        cik="0000320193",
        ticker="AAPL",
        legal_name="Apple Inc.",
        exchange="Nasdaq",
        country="US",
    )


def test_edgar_filing_valid_construction_and_invariants() -> None:
    company = _make_company()
    filing = EdgarFiling(
        accession_id=" 0000320193-24-000012 ",
        company=company,
        filing_type=FilingType("10-K"),
        filing_date=date(2024, 1, 31),
        period_end_date=date(2023, 12, 31),
        accepted_at=datetime(2024, 1, 31, 12, 0, 0),
        is_amendment=False,
        amendment_sequence=None,
        primary_document="10-k.htm",
        data_source="EDGAR",
    )

    assert filing.accession_id == "0000320193-24-000012"
    assert filing.period_end_date == date(2023, 12, 31)
    assert filing.filing_date == date(2024, 1, 31)
    assert filing.is_amendment is False
    assert filing.amendment_sequence is None
    assert filing.data_source == "EDGAR"


def test_edgar_filing_rejects_period_end_after_filing_date() -> None:
    company = _make_company()
    with pytest.raises(EdgarMappingError):
        EdgarFiling(
            accession_id="0000320193-24-000012",
            company=company,
            filing_type=FilingType("10-K"),
            filing_date=date(2024, 1, 31),
            period_end_date=date(2024, 2, 1),
            accepted_at=None,
            is_amendment=False,
            amendment_sequence=None,
            primary_document=None,
            data_source="EDGAR",
        )


def test_edgar_filing_rejects_invalid_amendment_configuration() -> None:
    company = _make_company()
    # Amendment without sequence.
    with pytest.raises(EdgarMappingError):
        EdgarFiling(
            accession_id="0000320193-24-000012",
            company=company,
            filing_type=FilingType("10-K"),
            filing_date=date(2024, 1, 31),
            period_end_date=None,
            accepted_at=None,
            is_amendment=True,
            amendment_sequence=None,
            primary_document=None,
            data_source="EDGAR",
        )

    # Non-amendment with sequence.
    with pytest.raises(EdgarMappingError):
        EdgarFiling(
            accession_id="0000320193-24-000012",
            company=company,
            filing_type=FilingType("10-K"),
            filing_date=date(2024, 1, 31),
            period_end_date=None,
            accepted_at=None,
            is_amendment=False,
            amendment_sequence=1,
            primary_document=None,
            data_source="EDGAR",
        )


def test_edgar_filing_rejects_empty_data_source() -> None:
    company = _make_company()
    with pytest.raises(EdgarMappingError):
        EdgarFiling(
            accession_id="0000320193-24-000012",
            company=company,
            filing_type=FilingType("10-K"),
            filing_date=date(2024, 1, 31),
            period_end_date=None,
            accepted_at=None,
            is_amendment=False,
            amendment_sequence=None,
            primary_document=None,
            data_source="  ",
        )
