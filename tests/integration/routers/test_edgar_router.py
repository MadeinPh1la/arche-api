# Copyright (c) Stacklion.
# SPDX-License-Identifier: MIT
"""Integration tests for EDGAR router.

These tests mount the EDGAR router in a minimal FastAPI app and override
the EDGAR controller dependency with a fake implementation. This keeps the
tests focused on HTTP behavior (params, envelopes, error handling) without
requiring real use-cases or repositories.
"""

from __future__ import annotations

from datetime import date
from typing import Any

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from stacklion_api.adapters.controllers.edgar_controller import EdgarController
from stacklion_api.adapters.routers.edgar_router import router as edgar_router
from stacklion_api.application.schemas.dto.edgar import (
    EdgarFilingDTO,
    EdgarStatementVersionDTO,
)
from stacklion_api.dependencies.edgar import get_edgar_controller
from stacklion_api.domain.enums.edgar import (
    AccountingStandard,
    FilingType,
    FiscalPeriod,
    StatementType,
)
from stacklion_api.domain.exceptions.edgar import EdgarIngestionError, EdgarMappingError


class _FakeEdgarController(EdgarController):  # type: ignore[misc]
    """Fake EDGAR controller for router integration tests."""

    def __init__(self) -> None:
        # Bypass BaseController init; we do not need real use-cases.
        pass  # type: ignore[no-untyped-call]

    async def list_filings(  # type: ignore[override]
        self,
        *,
        cik: str,
        filing_types,
        from_date,
        to_date,
        include_amendments: bool,
        page: int,
        page_size: int,
    ):
        dto = EdgarFilingDTO(
            accession_id="0000000001-24-000001",
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

    async def get_filing(  # type: ignore[override]
        self,
        *,
        cik: str,
        accession_id: str,
    ) -> EdgarFilingDTO:
        if accession_id == "missing":
            raise EdgarIngestionError(
                "Not found",
                details={"cik": cik, "accession_id": accession_id},
            )
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

    async def list_statements(  # type: ignore[override]
        self,
        *,
        cik: str,
        statement_type: StatementType,
        from_date,
        to_date,
        include_restated: bool,
        page: int,
        page_size: int,
    ):
        dto = EdgarStatementVersionDTO(
            accession_id="0000000001-24-000001",
            cik=cik,
            company_name="Test Co",
            statement_type=statement_type,
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

    async def get_statement_versions_for_filing(  # type: ignore[override]
        self,
        *,
        cik: str,
        accession_id: str,
        statement_type,
        include_restated: bool,
        include_normalized: bool,
    ):
        if accession_id == "bad-map":
            raise EdgarMappingError("Mapping error")
        filing = await self.get_filing(cik=cik, accession_id=accession_id)
        dto = EdgarStatementVersionDTO(
            accession_id=accession_id,
            cik=cik,
            company_name="Test Co",
            statement_type=statement_type or StatementType.INCOME_STATEMENT,
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
        return filing, [dto]


@pytest.fixture()
def client() -> TestClient:
    """Return a TestClient with the EDGAR router mounted and controller overridden."""
    app = FastAPI()
    app.include_router(edgar_router)

    fake_controller = _FakeEdgarController()
    app.dependency_overrides[get_edgar_controller] = lambda: fake_controller

    return TestClient(app)


def test_list_filings_happy_path(client: TestClient) -> None:
    """GET /v1/edgar/companies/{cik}/filings should return PaginatedEnvelope."""
    resp = client.get(
        "/v1/edgar/companies/0000000001/filings",
        params={
            "filing_types": "10-K",
            "from_date": "2023-01-01",
            "to_date": "2024-12-31",
            "include_amendments": "true",
        },
    )
    assert resp.status_code == 200, resp.text
    body: dict[str, Any] = resp.json()
    assert body["page"] == 1
    assert body["page_size"] >= 1
    assert body["total"] == 1
    assert len(body["items"]) == 1
    assert body["items"][0]["accession_id"] == "0000000001-24-000001"


def test_get_filing_happy_path(client: TestClient) -> None:
    """GET /v1/edgar/companies/{cik}/filings/{accession_id} should return SuccessEnvelope."""
    resp = client.get("/v1/edgar/companies/0000000001/filings/0000000001-24-000001")
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert "data" in body
    assert body["data"]["accession_id"] == "0000000001-24-000001"


def test_get_filing_not_found_maps_to_404(client: TestClient) -> None:
    """Not-found scenario from controller should map to 404 EDGAR_FILING_NOT_FOUND."""
    resp = client.get("/v1/edgar/companies/0000000001/filings/missing")
    assert resp.status_code == 404, resp.text
    body = resp.json()
    assert body["error"]["code"] == "EDGAR_FILING_NOT_FOUND"


def test_list_statements_happy_path(client: TestClient) -> None:
    """GET /v1/edgar/companies/{cik}/statements should return PaginatedEnvelope."""
    resp = client.get(
        "/v1/edgar/companies/0000000001/statements",
        params={"statement_type": StatementType.INCOME_STATEMENT.value},
    )
    assert resp.status_code == 200, resp.text
    body: dict[str, Any] = resp.json()
    assert body["page"] == 1
    assert body["total"] == 1
    assert len(body["items"]) == 1
    assert body["items"][0]["statement_type"] == StatementType.INCOME_STATEMENT.value


def test_list_statements_invalid_type_returns_400(client: TestClient) -> None:
    """Invalid statement_type should result in 400 VALIDATION_ERROR."""
    resp = client.get(
        "/v1/edgar/companies/0000000001/statements",
        params={"statement_type": "INVALID_TYPE"},
    )
    assert resp.status_code == 400, resp.text
    body = resp.json()
    assert body["error"]["code"] == "VALIDATION_ERROR"


def test_get_statement_versions_for_filing_happy_path(client: TestClient) -> None:
    """GET statement versions for a filing should include normalized_payload field set to null."""
    resp = client.get(
        "/v1/edgar/companies/0000000001/filings/0000000001-24-000001/statements",
        params={"include_normalized": "true"},
    )
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert "data" in body
    container = body["data"]
    assert container["filing"]["accession_id"] == "0000000001-24-000001"
    assert len(container["items"]) == 1
    assert "normalized_payload" in container["items"][0]
    assert container["items"][0]["normalized_payload"] is None


def test_get_statement_versions_for_filing_mapping_error(client: TestClient) -> None:
    """Mapping errors should result in 500 EDGAR_MAPPING_ERROR."""
    resp = client.get(
        "/v1/edgar/companies/0000000001/filings/bad-map/statements",
    )
    assert resp.status_code == 500, resp.text
    body = resp.json()
    assert body["error"]["code"] == "EDGAR_MAPPING_ERROR"
