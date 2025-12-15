# Copyright (c) Arche.
# SPDX-License-Identifier: MIT

from __future__ import annotations

from datetime import date

import pytest

from arche_api.adapters.gateways.edgar_gateway import HttpEdgarIngestionGateway
from arche_api.domain.entities.edgar_company import EdgarCompanyIdentity
from arche_api.domain.entities.edgar_filing import EdgarFiling
from arche_api.domain.enums.edgar import FilingType, StatementType
from arche_api.domain.exceptions.edgar import EdgarIngestionError
from arche_api.infrastructure.external_apis.edgar.client import EdgarClient


class _FakeEdgarClient(EdgarClient):
    """Test double that bypasses real HTTP calls."""

    def __init__(self, submissions_payload: dict) -> None:  # type: ignore[override]
        # Do not call super().__init__; tests only care about method behavior.
        self._payload = submissions_payload

    async def fetch_company_submissions(self, cik: str):  # type: ignore[override]
        return self._payload

    async def fetch_recent_filings(self, cik: str):  # type: ignore[override]
        return self._payload


def _make_submissions_payload() -> dict:
    """Return a minimal submissions JSON payload for tests."""
    return {
        "cik": "0000320193",
        "name": "Apple Inc.",
        "tickers": ["AAPL"],
        "filings": {
            "recent": {
                "accessionNumber": ["0000320193-24-000012", "0000320193-24-000013"],
                "filingDate": ["2024-01-31", "2024-02-15"],
                "reportDate": ["2023-12-31", "2024-01-31"],
                "form": ["10-K", "10-K/A"],
                "primaryDocument": ["10-k.htm", "10-ka.htm"],
                "acceptanceDateTime": ["20240131120000", "20240215120000"],
            }
        },
    }


@pytest.mark.asyncio
async def test_fetch_company_identity_happy_path() -> None:
    payload = _make_submissions_payload()
    client = _FakeEdgarClient(payload)
    gw = HttpEdgarIngestionGateway(client)

    identity = await gw.fetch_company_identity("320193")

    assert isinstance(identity, EdgarCompanyIdentity)
    assert identity.cik == "0000320193"
    assert identity.ticker == "AAPL"
    assert identity.legal_name == "Apple Inc."


@pytest.mark.asyncio
async def test_fetch_filings_for_company_filters_and_orders() -> None:
    payload = _make_submissions_payload()
    client = _FakeEdgarClient(payload)
    gw = HttpEdgarIngestionGateway(client)

    company = EdgarCompanyIdentity(
        cik="0000320193",
        ticker="AAPL",
        legal_name="Apple Inc.",
        exchange=None,
        country=None,
    )

    filings = await gw.fetch_filings_for_company(
        company=company,
        filing_types=[FilingType("10-K")],
        from_date=date(2024, 1, 1),
        to_date=date(2024, 12, 31),
        include_amendments=True,
        max_results=None,
    )

    assert len(filings) == 2
    # Ordered by filing_date desc, accession_id asc for ties.
    assert filings[0].is_amendment is True
    assert filings[0].filing_date == date(2024, 2, 15)
    assert filings[1].is_amendment is False
    assert filings[1].filing_date == date(2024, 1, 31)


@pytest.mark.asyncio
async def test_fetch_filings_for_company_excludes_amendments_when_requested() -> None:
    payload = _make_submissions_payload()
    client = _FakeEdgarClient(payload)
    gw = HttpEdgarIngestionGateway(client)

    company = EdgarCompanyIdentity(
        cik="0000320193",
        ticker="AAPL",
        legal_name="Apple Inc.",
        exchange=None,
        country=None,
    )

    filings = await gw.fetch_filings_for_company(
        company=company,
        filing_types=[FilingType("10-K")],
        from_date=date(2024, 1, 1),
        to_date=date(2024, 12, 31),
        include_amendments=False,
        max_results=None,
    )

    assert len(filings) == 1
    assert filings[0].is_amendment is False
    assert filings[0].amendment_sequence is None


@pytest.mark.asyncio
async def test_fetch_statement_versions_for_filing_metadata_only() -> None:
    payload = _make_submissions_payload()
    client = _FakeEdgarClient(payload)
    gw = HttpEdgarIngestionGateway(client)

    company = EdgarCompanyIdentity(
        cik="0000320193",
        ticker="AAPL",
        legal_name="Apple Inc.",
        exchange=None,
        country=None,
    )

    filing = EdgarFiling(
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

    versions = await gw.fetch_statement_versions_for_filing(
        filing,
        [StatementType.INCOME_STATEMENT, StatementType.BALANCE_SHEET],
    )

    assert len(versions) == 2
    v1, v2 = versions
    assert v1.statement_type == StatementType.INCOME_STATEMENT
    assert v2.statement_type == StatementType.BALANCE_SHEET
    assert v1.fiscal_year == 2023
    assert v1.statement_date == date(2023, 12, 31)
    assert v1.version_sequence == 1
    assert v2.version_sequence == 2


@pytest.mark.asyncio
async def test_ensure_submissions_root_rejects_invalid_root() -> None:
    client = _FakeEdgarClient({"unexpected": True})
    gw = HttpEdgarIngestionGateway(client)

    with pytest.raises(EdgarIngestionError):
        await gw.fetch_company_identity("320193")
