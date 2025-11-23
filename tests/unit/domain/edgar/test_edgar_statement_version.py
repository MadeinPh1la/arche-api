from __future__ import annotations

from datetime import date

import pytest

from stacklion_api.domain.entities.edgar_company import EdgarCompanyIdentity
from stacklion_api.domain.entities.edgar_filing import EdgarFiling
from stacklion_api.domain.entities.edgar_statement_version import EdgarStatementVersion
from stacklion_api.domain.enums.edgar import (
    AccountingStandard,
    FilingType,
    FiscalPeriod,
    StatementType,
)
from stacklion_api.domain.exceptions.edgar import EdgarMappingError


def _make_company() -> EdgarCompanyIdentity:
    return EdgarCompanyIdentity(
        cik="0000320193",
        ticker="AAPL",
        legal_name="Apple Inc.",
        exchange="Nasdaq",
        country="US",
    )


def _make_filing() -> EdgarFiling:
    company = _make_company()
    return EdgarFiling(
        accession_id="0000320193-24-000012",
        company=company,
        filing_type=FilingType("10-K"),
        filing_date=date(2024, 1, 31),
        period_end_date=date(2023, 12, 31),
        accepted_at=None,
        is_amendment=False,
        amendment_sequence=None,
        primary_document="10-k.htm",
        data_source="EDGAR",
    )


def test_edgar_statement_version_valid_construction_and_invariants() -> None:
    filing = _make_filing()
    version = EdgarStatementVersion(
        company=filing.company,
        filing=filing,
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
        accession_id=filing.accession_id,
        filing_date=filing.filing_date,
    )

    assert version.company == filing.company
    assert version.filing is filing
    assert version.accession_id == filing.accession_id
    assert version.filing_date == filing.filing_date
    assert version.currency == "USD"
    assert version.version_sequence == 1
    assert version.version_source == "EDGAR_METADATA_ONLY"


def test_edgar_statement_version_rejects_statement_date_after_filing_date() -> None:
    filing = _make_filing()
    with pytest.raises(EdgarMappingError):
        EdgarStatementVersion(
            company=filing.company,
            filing=filing,
            statement_type=StatementType.INCOME_STATEMENT,
            accounting_standard=AccountingStandard.US_GAAP,
            statement_date=date(2024, 2, 1),
            fiscal_year=2024,
            fiscal_period=FiscalPeriod.FY,
            currency="USD",
            is_restated=False,
            restatement_reason=None,
            version_source="EDGAR_METADATA_ONLY",
            version_sequence=1,
            accession_id=filing.accession_id,
            filing_date=filing.filing_date,
        )


def test_edgar_statement_version_rejects_mismatched_accession_or_filing_date() -> None:
    filing = _make_filing()
    with pytest.raises(EdgarMappingError):
        EdgarStatementVersion(
            company=filing.company,
            filing=filing,
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
            accession_id="WRONG",
            filing_date=filing.filing_date,
        )

    with pytest.raises(EdgarMappingError):
        EdgarStatementVersion(
            company=filing.company,
            filing=filing,
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
            accession_id=filing.accession_id,
            filing_date=date(2024, 1, 30),
        )


def test_edgar_statement_version_rejects_invalid_metadata() -> None:
    filing = _make_filing()

    with pytest.raises(EdgarMappingError):
        EdgarStatementVersion(
            company=filing.company,
            filing=filing,
            statement_type=StatementType.INCOME_STATEMENT,
            accounting_standard=AccountingStandard.US_GAAP,
            statement_date=date(2023, 12, 31),
            fiscal_year=0,
            fiscal_period=FiscalPeriod.FY,
            currency="USD",
            is_restated=False,
            restatement_reason=None,
            version_source="EDGAR_METADATA_ONLY",
            version_sequence=1,
            accession_id=filing.accession_id,
            filing_date=filing.filing_date,
        )

    with pytest.raises(EdgarMappingError):
        EdgarStatementVersion(
            company=filing.company,
            filing=filing,
            statement_type=StatementType.INCOME_STATEMENT,
            accounting_standard=AccountingStandard.US_GAAP,
            statement_date=date(2023, 12, 31),
            fiscal_year=2023,
            fiscal_period=FiscalPeriod.FY,
            currency="  ",
            is_restated=False,
            restatement_reason=None,
            version_source="EDGAR_METADATA_ONLY",
            version_sequence=1,
            accession_id=filing.accession_id,
            filing_date=filing.filing_date,
        )

    with pytest.raises(EdgarMappingError):
        EdgarStatementVersion(
            company=filing.company,
            filing=filing,
            statement_type=StatementType.INCOME_STATEMENT,
            accounting_standard=AccountingStandard.US_GAAP,
            statement_date=date(2023, 12, 31),
            fiscal_year=2023,
            fiscal_period=FiscalPeriod.FY,
            currency="USD",
            is_restated=False,
            restatement_reason=None,
            version_source="  ",
            version_sequence=1,
            accession_id=filing.accession_id,
            filing_date=filing.filing_date,
        )

    with pytest.raises(EdgarMappingError):
        EdgarStatementVersion(
            company=filing.company,
            filing=filing,
            statement_type=StatementType.INCOME_STATEMENT,
            accounting_standard=AccountingStandard.US_GAAP,
            statement_date=date(2023, 12, 31),
            fiscal_year=2023,
            fiscal_period=FiscalPeriod.FY,
            currency="USD",
            is_restated=True,
            restatement_reason=None,
            version_source="EDGAR_METADATA_ONLY",
            version_sequence=1,
            accession_id=filing.accession_id,
            filing_date=filing.filing_date,
        )

    with pytest.raises(EdgarMappingError):
        EdgarStatementVersion(
            company=filing.company,
            filing=filing,
            statement_type=StatementType.INCOME_STATEMENT,
            accounting_standard=AccountingStandard.US_GAAP,
            statement_date=date(2023, 12, 31),
            fiscal_year=2023,
            fiscal_period=FiscalPeriod.FY,
            currency="USD",
            is_restated=False,
            restatement_reason="should be None",
            version_source="EDGAR_METADATA_ONLY",
            version_sequence=1,
            accession_id=filing.accession_id,
            filing_date=filing.filing_date,
        )
