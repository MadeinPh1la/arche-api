# Copyright (c) Stacklion.
# SPDX-License-Identifier: MIT
"""Unit tests for EDGAR HTTP schemas."""

from __future__ import annotations

from datetime import UTC, date, datetime

from stacklion_api.adapters.schemas.http.edgar_schemas import (
    EdgarFilingHTTP,
    EdgarStatementVersionHTTP,
    EdgarStatementVersionListHTTP,
    EdgarStatementVersionSummaryHTTP,
    NormalizedFactHTTP,
    NormalizedStatementHTTP,
)
from stacklion_api.domain.enums.edgar import (
    AccountingStandard,
    FilingType,
    FiscalPeriod,
    StatementType,
)


def test_edgar_filing_http_roundtrip() -> None:
    """EdgarFilingHTTP should accept and dump expected fields."""
    filing = EdgarFilingHTTP(
        accession_id="0000320193-24-000012",
        cik="0000320193",
        company_name="Apple Inc.",
        filing_type=FilingType("10-K"),
        filing_date=date(2024, 10, 25),
        period_end_date=date(2024, 9, 28),
        is_amendment=False,
        amendment_sequence=None,
        primary_document="aapl-20240928.htm",
        accepted_at=datetime(2024, 10, 25, 16, 5, tzinfo=UTC),
    )

    dumped = filing.model_dump_http()
    assert dumped["accession_id"] == "0000320193-24-000012"
    assert dumped["cik"] == "0000320193"
    assert dumped["filing_type"] == "10-K"
    assert dumped["is_amendment"] is False
    assert dumped["period_end_date"] == "2024-09-28"


def test_normalized_fact_and_statement_http_roundtrip() -> None:
    """NormalizedFactHTTP and NormalizedStatementHTTP should serialize cleanly."""
    fact = NormalizedFactHTTP(
        metric="REVENUE",
        label="Revenue",
        unit="USD",
        period_start=date(2024, 1, 1),
        period_end=date(2024, 3, 31),
        value="123456.78",
        dimension={"segment": "US"},
        source_line_item="Net sales",
    )

    stmt = NormalizedStatementHTTP(
        statement_type=StatementType.INCOME_STATEMENT,
        accounting_standard=AccountingStandard.US_GAAP,
        fiscal_year=2024,
        fiscal_period=FiscalPeriod.Q1,
        currency="USD",
        facts=[fact],
    )

    dumped = stmt.model_dump_http()
    assert dumped["statement_type"] == StatementType.INCOME_STATEMENT.value
    assert dumped["accounting_standard"] == AccountingStandard.US_GAAP.value
    assert dumped["fiscal_year"] == 2024
    assert dumped["currency"] == "USD"
    assert dumped["facts"][0]["metric"] == "REVENUE"
    assert dumped["facts"][0]["value"] == "123456.78"


def test_edgar_statement_version_http_with_normalized_payload_none() -> None:
    """EdgarStatementVersionHTTP should default normalized_payload to None."""
    version = EdgarStatementVersionHTTP(
        accession_id="0000320193-24-000012",
        cik="0000320193",
        company_name="Apple Inc.",
        statement_type=StatementType.INCOME_STATEMENT,
        accounting_standard=AccountingStandard.US_GAAP,
        statement_date=date(2024, 9, 28),
        fiscal_year=2024,
        fiscal_period=FiscalPeriod.FY,
        currency="USD",
        is_restated=False,
        restatement_reason=None,
        version_source="EDGAR_METADATA_ONLY",
        version_sequence=1,
        filing_type=FilingType("10-K"),
        filing_date=date(2024, 10, 25),
        normalized_payload=None,
    )

    dumped = version.model_dump_http()
    assert "normalized_payload" in dumped
    assert dumped["normalized_payload"] is None


def test_edgar_statement_version_list_http_compose() -> None:
    """EdgarStatementVersionListHTTP should compose filing and items."""
    filing = EdgarFilingHTTP(
        accession_id="0000320193-24-000012",
        cik="0000320193",
        company_name="Apple Inc.",
        filing_type=FilingType("10-K"),
        filing_date=date(2024, 10, 25),
        period_end_date=date(2024, 9, 28),
        is_amendment=False,
        amendment_sequence=None,
        primary_document="aapl-20240928.htm",
        accepted_at=None,
    )
    summary = EdgarStatementVersionSummaryHTTP(
        accession_id="0000320193-24-000012",
        cik="0000320193",
        company_name="Apple Inc.",
        statement_type=StatementType.INCOME_STATEMENT,
        accounting_standard=AccountingStandard.US_GAAP,
        statement_date=date(2024, 9, 28),
        fiscal_year=2024,
        fiscal_period=FiscalPeriod.FY,
        currency="USD",
        is_restated=False,
        restatement_reason=None,
        version_source="EDGAR_METADATA_ONLY",
        version_sequence=1,
        filing_type=FilingType("10-K"),
        filing_date=date(2024, 10, 25),
    )

    full = EdgarStatementVersionHTTP(
        accession_id=summary.accession_id,
        cik=summary.cik,
        company_name=summary.company_name,
        statement_type=summary.statement_type,
        accounting_standard=summary.accounting_standard,
        statement_date=summary.statement_date,
        fiscal_year=summary.fiscal_year,
        fiscal_period=summary.fiscal_period,
        currency=summary.currency,
        is_restated=summary.is_restated,
        restatement_reason=summary.restatement_reason,
        version_source=summary.version_source,
        version_sequence=summary.version_sequence,
        filing_type=summary.filing_type,
        filing_date=summary.filing_date,
        normalized_payload=None,
    )

    container = EdgarStatementVersionListHTTP(filing=filing, items=[full])
    dumped = container.model_dump_http()
    assert dumped["filing"]["accession_id"] == filing.accession_id
    assert len(dumped["items"]) == 1
    assert dumped["items"][0]["version_sequence"] == 1
