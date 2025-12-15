# tests/integration/adapters/routers/test_edgar_router_override_trace.py
# Copyright (c)
# SPDX-License-Identifier: MIT
"""Integration tests for EDGAR XBRL override trace endpoint.

These tests mount the EDGAR router in a minimal FastAPI app and override
the EDGAR UnitOfWork dependency and use-case wiring. The goal is to verify
HTTP-level behavior for the override trace endpoint:

    - Request parameter binding.
    - SuccessEnvelope[StatementOverrideTraceHTTP] response shape.
    - Validation errors mapped to canonical ErrorEnvelope.
    - Domain errors mapped to canonical ErrorEnvelope.
"""

from __future__ import annotations

from typing import Any

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

import arche_api.adapters.routers.edgar_router as edgar_router_module
from arche_api.adapters.dependencies.edgar_uow import get_edgar_uow
from arche_api.adapters.schemas.http.edgar_overrides_schemas import (
    StatementOverrideTraceHTTP,
)
from arche_api.adapters.schemas.http.envelopes import ErrorEnvelope, SuccessEnvelope
from arche_api.domain.enums.edgar import FiscalPeriod, StatementType
from arche_api.domain.exceptions.edgar import EdgarIngestionError


class _FakeOverrideTraceDTO:
    """Minimal DTO-like object for override trace tests.

    This type mirrors the public attributes accessed by the presenter stub.
    It does not depend on the real application DTO implementation.
    """

    def __init__(
        self,
        *,
        cik: str,
        statement_type: str,
        fiscal_year: int,
        fiscal_period: str,
        version_sequence: int,
        gaap_concept: str | None,
        canonical_metric_code: str | None,
        dimension_key: str | None,
        total_facts_evaluated: int,
        total_facts_remapped: int,
        total_facts_suppressed: int,
    ) -> None:
        self.cik = cik
        self.statement_type = statement_type
        self.fiscal_year = fiscal_year
        self.fiscal_period = fiscal_period
        self.version_sequence = version_sequence
        self.gaap_concept = gaap_concept
        self.canonical_metric_code = canonical_metric_code
        self.dimension_key = dimension_key
        self.total_facts_evaluated = total_facts_evaluated
        self.total_facts_remapped = total_facts_remapped
        self.total_facts_suppressed = total_facts_suppressed
        # The real DTO exposes a rules collection; for these tests we can keep it empty.
        self.rules: list[Any] = []


@pytest.fixture()
def app() -> FastAPI:
    """Return a FastAPI app with the EDGAR router mounted."""
    app = FastAPI()
    app.include_router(edgar_router_module.router)
    return app


@pytest.fixture()
def client(app: FastAPI) -> TestClient:
    """Return a TestClient for the mounted EDGAR router."""
    return TestClient(app)


def _override_uow(app: FastAPI) -> None:
    """Override the EDGAR UnitOfWork dependency with a no-op dummy."""

    class _DummyUoW:
        """Minimal dummy UnitOfWork for tests.

        The override trace use-case under test is stubbed and does not
        interact with the UoW, so this can remain empty.
        """

        async def __aenter__(self) -> _DummyUoW:  # pragma: no cover - defensive
            return self

        async def __aexit__(self, exc_type, exc, tb) -> None:  # pragma: no cover - defensive
            return None

    app.dependency_overrides[get_edgar_uow] = lambda: _DummyUoW()


def test_get_statement_override_trace_happy_path(
    app: FastAPI,
    client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Happy path should return SuccessEnvelope[StatementOverrideTraceHTTP]."""
    _override_uow(app)

    # Stub the use-case to construct a DTO-like object from the request.
    class _FakeUseCase:
        def __init__(self, uow: object) -> None:  # pragma: no cover - trivial
            self._uow = uow

        async def execute(self, req: Any) -> _FakeOverrideTraceDTO:
            # req is the real GetStatementOverrideTraceRequest; we rely on
            # attribute names only and avoid importing its type.
            return _FakeOverrideTraceDTO(
                cik=req.cik,
                statement_type=req.statement_type.value,
                fiscal_year=req.fiscal_year,
                fiscal_period=req.fiscal_period.value,
                version_sequence=req.version_sequence,
                gaap_concept=req.gaap_concept,
                canonical_metric_code=req.canonical_metric_code,
                dimension_key=req.dimension_key,
                total_facts_evaluated=10,
                total_facts_remapped=3,
                total_facts_suppressed=1,
            )

    monkeypatch.setattr(
        edgar_router_module,
        "GetStatementOverrideTraceUseCase",
        _FakeUseCase,
    )

    # Stub the presenter to map the fake DTO into the HTTP schema + envelope.
    def _fake_present(dto: _FakeOverrideTraceDTO) -> SuccessEnvelope[StatementOverrideTraceHTTP]:
        payload = StatementOverrideTraceHTTP(
            cik=dto.cik,
            statement_type=dto.statement_type,
            fiscal_year=dto.fiscal_year,
            fiscal_period=dto.fiscal_period,
            version_sequence=dto.version_sequence,
            gaap_concept=dto.gaap_concept,
            canonical_metric_code=dto.canonical_metric_code,
            dimension_key=dto.dimension_key,
            total_facts_evaluated=dto.total_facts_evaluated,
            total_facts_remapped=dto.total_facts_remapped,
            total_facts_suppressed=dto.total_facts_suppressed,
            rules=[],
        )
        return SuccessEnvelope[StatementOverrideTraceHTTP](data=payload)

    monkeypatch.setattr(
        edgar_router_module,
        "present_statement_override_trace",
        _fake_present,
    )

    resp = client.get(
        "/v1/edgar/companies/0000000001/statements/overrides/trace",
        params={
            "statement_type": StatementType.INCOME_STATEMENT.value,
            "fiscal_year": 2024,
            "fiscal_period": FiscalPeriod.FY.value,
            "version_sequence": 1,
            "gaap_concept": "us-gaap:Revenues",
            "canonical_metric_code": "REVENUE",
            "dimension_key": "SEGMENT=US",
        },
    )

    assert resp.status_code == 200, resp.text
    body = resp.json()

    # Envelope shape
    assert "data" in body
    data = body["data"]

    # Identity fields
    assert data["cik"] == "0000000001"
    assert data["statement_type"] == "INCOME_STATEMENT"
    assert data["fiscal_year"] == 2024
    assert data["fiscal_period"] == "FY"
    assert data["version_sequence"] == 1

    # Filters
    assert data["gaap_concept"] == "us-gaap:Revenues"
    assert data["canonical_metric_code"] == "REVENUE"
    assert data["dimension_key"] == "SEGMENT=US"

    # Aggregate counts
    assert data["total_facts_evaluated"] == 10
    assert data["total_facts_remapped"] == 3
    assert data["total_facts_suppressed"] == 1

    # Rules collection is present (empty in this stub)
    assert "rules" in data
    assert isinstance(data["rules"], list)


def test_get_statement_override_trace_invalid_statement_type_returns_400(
    app: FastAPI,
    client: TestClient,
) -> None:
    """Invalid statement_type should result in 400 VALIDATION_ERROR."""
    _override_uow(app)

    resp = client.get(
        "/v1/edgar/companies/0000000001/statements/overrides/trace",
        params={
            "statement_type": "INVALID_TYPE",
            "fiscal_year": 2024,
            "fiscal_period": FiscalPeriod.FY.value,
            "version_sequence": 1,
        },
    )

    assert resp.status_code == 400, resp.text
    body = ErrorEnvelope.model_validate(resp.json())
    assert body.error.code == "VALIDATION_ERROR"
    assert body.error.http_status == 400


def test_get_statement_override_trace_invalid_fiscal_period_returns_400(
    app: FastAPI,
    client: TestClient,
) -> None:
    """Invalid fiscal_period should result in 400 VALIDATION_ERROR."""
    _override_uow(app)

    resp = client.get(
        "/v1/edgar/companies/0000000001/statements/overrides/trace",
        params={
            "statement_type": StatementType.INCOME_STATEMENT.value,
            "fiscal_year": 2024,
            "fiscal_period": "INVALID_PERIOD",
            "version_sequence": 1,
        },
    )

    assert resp.status_code == 400, resp.text
    body = ErrorEnvelope.model_validate(resp.json())
    assert body.error.code == "VALIDATION_ERROR"
    assert body.error.http_status == 400


def test_get_statement_override_trace_ingestion_error_maps_to_404(
    app: FastAPI,
    client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """EdgarIngestionError from the use-case should map to 404 EDGAR_STATEMENT_NOT_FOUND."""
    _override_uow(app)

    class _UseCaseRaisesIngestionError:
        def __init__(self, uow: object) -> None:  # pragma: no cover - trivial
            self._uow = uow

        async def execute(self, req: Any) -> None:  # pragma: no cover - trivial
            raise EdgarIngestionError(
                "Not found",
                details={
                    "cik": req.cik,
                    "statement_type": req.statement_type.value,
                    "fiscal_year": req.fiscal_year,
                    "fiscal_period": req.fiscal_period.value,
                    "version_sequence": req.version_sequence,
                },
            )

    monkeypatch.setattr(
        edgar_router_module,
        "GetStatementOverrideTraceUseCase",
        _UseCaseRaisesIngestionError,
    )

    resp = client.get(
        "/v1/edgar/companies/0000000001/statements/overrides/trace",
        params={
            "statement_type": StatementType.INCOME_STATEMENT.value,
            "fiscal_year": 2024,
            "fiscal_period": FiscalPeriod.FY.value,
            "version_sequence": 1,
        },
    )

    assert resp.status_code == 404, resp.text
    body = ErrorEnvelope.model_validate(resp.json())
    assert body.error.code == "EDGAR_STATEMENT_NOT_FOUND"
    assert body.error.http_status == 404
