# tests/unit/adapters/routers/test_edgar_router_restatements.py
# Copyright (c)
# SPDX-License-Identifier: MIT
"""HTTP tests for EDGAR restatement delta and ledger endpoints.

Scope:
    - Validate happy-path behavior for:
        * GET /v1/edgar/statements/restatements/delta
        * GET /v1/edgar/statements/restatements/ledger
    - Ensure request validation and error mapping behave as expected.
    - Assert that the router + presenter wiring shape the HTTP envelope
      correctly from controller DTOs.
"""

from __future__ import annotations

import pytest
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient

from arche_api.adapters.routers.edgar_router import router as edgar_router
from arche_api.application.schemas.dto.edgar import (
    ComputeRestatementDeltaResultDTO,
    GetRestatementLedgerResultDTO,
    RestatementLedgerEntryDTO,
    RestatementMetricDeltaDTO,
    RestatementSummaryDTO,
)
from arche_api.dependencies.edgar import get_edgar_controller
from arche_api.domain.enums.edgar import FiscalPeriod, StatementType
from arche_api.domain.exceptions.edgar import EdgarIngestionError, EdgarMappingError


@pytest.fixture
def app() -> FastAPI:
    """FastAPI app instance including only the EDGAR router."""
    app = FastAPI()
    app.include_router(edgar_router)
    return app


# ---------------------------------------------------------------------------
# Fakes
# ---------------------------------------------------------------------------


class _FakeRestatementController:
    """Fake controller returning fixed restatement DTOs."""

    def __init__(
        self,
        delta_result: ComputeRestatementDeltaResultDTO | None = None,
        ledger_result: GetRestatementLedgerResultDTO | None = None,
        delta_exc: Exception | None = None,
        ledger_exc: Exception | None = None,
    ) -> None:
        self._delta_result = delta_result
        self._ledger_result = ledger_result
        self._delta_exc = delta_exc
        self._ledger_exc = ledger_exc

    async def compute_restatement_delta(  # noqa: D401 - simple fake
        self,
        *,
        cik,
        statement_type,
        fiscal_year,
        fiscal_period,
        from_version_sequence,
        to_version_sequence,
    ) -> ComputeRestatementDeltaResultDTO:
        """Return a preconfigured restatement delta result or raise."""
        assert isinstance(cik, str)
        assert isinstance(statement_type, StatementType)
        assert isinstance(fiscal_year, int)
        assert isinstance(fiscal_period, FiscalPeriod)
        assert isinstance(from_version_sequence, int)
        assert isinstance(to_version_sequence, int)

        if self._delta_exc is not None:
            raise self._delta_exc
        assert self._delta_result is not None
        return self._delta_result

    async def get_restatement_ledger(  # noqa: D401 - simple fake
        self,
        *,
        cik,
        statement_type,
        fiscal_year,
        fiscal_period,
    ) -> GetRestatementLedgerResultDTO:
        """Return a preconfigured restatement ledger result or raise."""
        assert isinstance(cik, str)
        assert isinstance(statement_type, StatementType)
        assert isinstance(fiscal_year, int)
        assert isinstance(fiscal_period, FiscalPeriod)

        if self._ledger_exc is not None:
            raise self._ledger_exc
        assert self._ledger_result is not None
        return self._ledger_result


def _make_delta_result() -> ComputeRestatementDeltaResultDTO:
    """Build a minimal but valid restatement delta DTO."""
    summary = RestatementSummaryDTO(
        total_metrics_compared=1,
        total_metrics_changed=1,
        has_material_change=True,
    )
    deltas = [
        RestatementMetricDeltaDTO(
            metric="REVENUE",
            old_value="100",
            new_value="120",
            diff="20",
        )
    ]
    return ComputeRestatementDeltaResultDTO(
        cik="0000320193",
        statement_type=StatementType.INCOME_STATEMENT,
        fiscal_year=2024,
        fiscal_period=FiscalPeriod.FY,
        from_version_sequence=1,
        to_version_sequence=2,
        summary=summary,
        deltas=deltas,
    )


def _make_ledger_result() -> GetRestatementLedgerResultDTO:
    """Build a minimal but valid restatement ledger DTO."""
    summary = RestatementSummaryDTO(
        total_metrics_compared=1,
        total_metrics_changed=1,
        has_material_change=True,
    )
    deltas = [
        RestatementMetricDeltaDTO(
            metric="REVENUE",
            old_value="100",
            new_value="120",
            diff="20",
        )
    ]
    entry = RestatementLedgerEntryDTO(
        from_version_sequence=1,
        to_version_sequence=2,
        summary=summary,
        deltas=deltas,
    )
    return GetRestatementLedgerResultDTO(
        cik="0000320193",
        statement_type=StatementType.INCOME_STATEMENT,
        fiscal_year=2024,
        fiscal_period=FiscalPeriod.FY,
        entries=[entry],
    )


# ---------------------------------------------------------------------------
# Tests: delta endpoint
# ---------------------------------------------------------------------------


@pytest.mark.anyio
async def test_get_restatement_delta_happy_path(app: FastAPI) -> None:
    """Happy path: endpoint returns a success envelope with delta payload."""
    delta_result = _make_delta_result()
    fake_controller = _FakeRestatementController(delta_result=delta_result)

    app.dependency_overrides[get_edgar_controller] = lambda: fake_controller

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        resp = await client.get(
            "/v1/edgar/statements/restatements/delta",
            params={
                "cik": "0000320193",
                "statement_type": "INCOME_STATEMENT",
                "fiscal_year": 2024,
                "fiscal_period": "FY",
                "from_version_sequence": 1,
                "to_version_sequence": 2,
            },
        )

    assert resp.status_code == 200
    payload = resp.json()

    assert "data" in payload
    data = payload["data"]

    assert data["cik"] == "0000320193"
    assert data["statement_type"] == "INCOME_STATEMENT"
    assert data["fiscal_year"] == 2024
    assert data["fiscal_period"] == "FY"
    assert data["from_version_sequence"] == 1
    assert data["to_version_sequence"] == 2

    summary = data["summary"]
    assert summary["total_metrics_compared"] == 1
    assert summary["total_metrics_changed"] == 1
    assert summary["has_material_change"] is True

    deltas = data["deltas"]
    assert isinstance(deltas, list)
    assert len(deltas) == 1
    m = deltas[0]
    assert m["metric"] == "REVENUE"
    assert m["old_value"] == "100"
    assert m["new_value"] == "120"
    assert m["diff"] == "20"


@pytest.mark.anyio
async def test_get_restatement_delta_invalid_statement_type(app: FastAPI) -> None:
    """Invalid statement_type should return 400 with a validation error envelope."""
    fake_controller = _FakeRestatementController(delta_result=_make_delta_result())
    app.dependency_overrides[get_edgar_controller] = lambda: fake_controller

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        resp = await client.get(
            "/v1/edgar/statements/restatements/delta",
            params={
                "cik": "0000320193",
                "statement_type": "NOT_A_STATEMENT_TYPE",
                "fiscal_year": 2024,
                "fiscal_period": "FY",
                "from_version_sequence": 1,
                "to_version_sequence": 2,
            },
        )

    assert resp.status_code == 400
    body = resp.json()
    assert "error" in body
    err = body["error"]
    assert err["code"] == "VALIDATION_ERROR"
    assert err["http_status"] == 400
    assert err["details"]["statement_type"] == "NOT_A_STATEMENT_TYPE"


@pytest.mark.anyio
async def test_get_restatement_delta_invalid_fiscal_period(app: FastAPI) -> None:
    """Invalid fiscal_period should return 400 with a validation error envelope."""
    fake_controller = _FakeRestatementController(delta_result=_make_delta_result())
    app.dependency_overrides[get_edgar_controller] = lambda: fake_controller

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        resp = await client.get(
            "/v1/edgar/statements/restatements/delta",
            params={
                "cik": "0000320193",
                "statement_type": "INCOME_STATEMENT",
                "fiscal_year": 2024,
                "fiscal_period": "NOT_A_PERIOD",
                "from_version_sequence": 1,
                "to_version_sequence": 2,
            },
        )

    assert resp.status_code == 400
    body = resp.json()
    err = body["error"]
    assert err["code"] == "VALIDATION_ERROR"
    assert err["http_status"] == 400
    assert err["details"]["fiscal_period"] == "NOT_A_PERIOD"


@pytest.mark.anyio
async def test_get_restatement_delta_invalid_version_order(app: FastAPI) -> None:
    """from_version_sequence > to_version_sequence should return 400."""
    fake_controller = _FakeRestatementController(delta_result=_make_delta_result())
    app.dependency_overrides[get_edgar_controller] = lambda: fake_controller

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        resp = await client.get(
            "/v1/edgar/statements/restatements/delta",
            params={
                "cik": "0000320193",
                "statement_type": "INCOME_STATEMENT",
                "fiscal_year": 2024,
                "fiscal_period": "FY",
                "from_version_sequence": 3,
                "to_version_sequence": 2,
            },
        )

    assert resp.status_code == 400
    body = resp.json()
    err = body["error"]
    assert err["code"] == "VALIDATION_ERROR"
    assert err["http_status"] == 400
    assert err["details"]["from_version_sequence"] == 3
    assert err["details"]["to_version_sequence"] == 2


@pytest.mark.anyio
async def test_get_restatement_delta_edgar_mapping_error(app: FastAPI) -> None:
    """EdgarMappingError from the controller should be mapped to a 500 envelope."""
    fake_controller = _FakeRestatementController(
        delta_exc=EdgarMappingError("bad request", details={"field": "value"}),
    )
    app.dependency_overrides[get_edgar_controller] = lambda: fake_controller

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        resp = await client.get(
            "/v1/edgar/statements/restatements/delta",
            params={
                "cik": "0000320193",
                "statement_type": "INCOME_STATEMENT",
                "fiscal_year": 2024,
                "fiscal_period": "FY",
                "from_version_sequence": 1,
                "to_version_sequence": 2,
            },
        )

    assert resp.status_code == 500
    body = resp.json()
    err = body["error"]
    assert err["code"] == "EDGAR_MAPPING_ERROR"
    assert err["http_status"] == 500
    assert err["message"] == "bad request"
    assert isinstance(err.get("details", {}), dict)


@pytest.mark.anyio
async def test_get_restatement_delta_edgar_upstream_error(app: FastAPI) -> None:
    """EdgarIngestionError should be mapped to a 502 envelope."""
    fake_controller = _FakeRestatementController(
        delta_exc=EdgarIngestionError("upstream failure", details={"upstream": "edgar"}),
    )
    app.dependency_overrides[get_edgar_controller] = lambda: fake_controller

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        resp = await client.get(
            "/v1/edgar/statements/restatements/delta",
            params={
                "cik": "0000320193",
                "statement_type": "INCOME_STATEMENT",
                "fiscal_year": 2024,
                "fiscal_period": "FY",
                "from_version_sequence": 1,
                "to_version_sequence": 2,
            },
        )

    assert resp.status_code == 502
    body = resp.json()
    err = body["error"]
    assert err["code"] == "EDGAR_UPSTREAM_ERROR"
    assert err["http_status"] == 502
    assert err["message"] == "upstream failure"
    assert isinstance(err.get("details", {}), dict)


# ---------------------------------------------------------------------------
# Tests: ledger endpoint
# ---------------------------------------------------------------------------


@pytest.mark.anyio
async def test_get_restatement_ledger_happy_path(app: FastAPI) -> None:
    """Happy path: endpoint returns a success envelope with ledger payload."""
    ledger_result = _make_ledger_result()
    fake_controller = _FakeRestatementController(ledger_result=ledger_result)
    app.dependency_overrides[get_edgar_controller] = lambda: fake_controller

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        resp = await client.get(
            "/v1/edgar/statements/restatements/ledger",
            params={
                "cik": "0000320193",
                "statement_type": "INCOME_STATEMENT",
                "fiscal_year": 2024,
                "fiscal_period": "FY",
            },
        )

    assert resp.status_code == 200
    payload = resp.json()
    data = payload["data"]

    assert data["cik"] == "0000320193"
    assert data["statement_type"] == "INCOME_STATEMENT"
    assert data["fiscal_year"] == 2024
    assert data["fiscal_period"] == "FY"
    assert data["total_hops"] == 1

    entries = data["entries"]
    assert isinstance(entries, list)
    assert len(entries) == 1

    entry = entries[0]
    assert entry["from_version_sequence"] == 1
    assert entry["to_version_sequence"] == 2

    summary = entry["summary"]
    assert summary["total_metrics_compared"] == 1
    assert summary["total_metrics_changed"] == 1
    assert summary["has_material_change"] is True

    deltas = entry["deltas"]
    assert len(deltas) == 1
    m = deltas[0]
    assert m["metric"] == "REVENUE"
    assert m["old_value"] == "100"
    assert m["new_value"] == "120"
    assert m["diff"] == "20"


@pytest.mark.anyio
async def test_get_restatement_ledger_invalid_statement_type(app: FastAPI) -> None:
    """Invalid statement_type should return 400 with a validation error envelope."""
    fake_controller = _FakeRestatementController(ledger_result=_make_ledger_result())
    app.dependency_overrides[get_edgar_controller] = lambda: fake_controller

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        resp = await client.get(
            "/v1/edgar/statements/restatements/ledger",
            params={
                "cik": "0000320193",
                "statement_type": "NOT_A_STATEMENT_TYPE",
                "fiscal_year": 2024,
                "fiscal_period": "FY",
            },
        )

    assert resp.status_code == 400
    body = resp.json()
    err = body["error"]
    assert err["code"] == "VALIDATION_ERROR"
    assert err["http_status"] == 400
    assert err["details"]["statement_type"] == "NOT_A_STATEMENT_TYPE"


@pytest.mark.anyio
async def test_get_restatement_ledger_invalid_fiscal_period(app: FastAPI) -> None:
    """Invalid fiscal_period should return 400 with a validation error envelope."""
    fake_controller = _FakeRestatementController(ledger_result=_make_ledger_result())
    app.dependency_overrides[get_edgar_controller] = lambda: fake_controller

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        resp = await client.get(
            "/v1/edgar/statements/restatements/ledger",
            params={
                "cik": "0000320193",
                "statement_type": "INCOME_STATEMENT",
                "fiscal_year": 2024,
                "fiscal_period": "NOT_A_PERIOD",
            },
        )

    assert resp.status_code == 400
    body = resp.json()
    err = body["error"]
    assert err["code"] == "VALIDATION_ERROR"
    assert err["http_status"] == 400
    assert err["details"]["fiscal_period"] == "NOT_A_PERIOD"


@pytest.mark.anyio
async def test_get_restatement_ledger_edgar_mapping_error(app: FastAPI) -> None:
    """EdgarMappingError from the controller should be mapped to a 500 envelope."""
    fake_controller = _FakeRestatementController(
        ledger_exc=EdgarMappingError("bad ledger request", details={"field": "value"}),
    )
    app.dependency_overrides[get_edgar_controller] = lambda: fake_controller

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        resp = await client.get(
            "/v1/edgar/statements/restatements/ledger",
            params={
                "cik": "0000320193",
                "statement_type": "INCOME_STATEMENT",
                "fiscal_year": 2024,
                "fiscal_period": "FY",
            },
        )

    assert resp.status_code == 500
    body = resp.json()
    err = body["error"]
    assert err["code"] == "EDGAR_MAPPING_ERROR"
    assert err["http_status"] == 500
    assert err["message"] == "bad ledger request"
    assert isinstance(err.get("details", {}), dict)


@pytest.mark.anyio
async def test_get_restatement_ledger_edgar_upstream_error(app: FastAPI) -> None:
    """EdgarIngestionError should be mapped to a 502 envelope."""
    fake_controller = _FakeRestatementController(
        ledger_exc=EdgarIngestionError("upstream failure", details={"upstream": "edgar"}),
    )
    app.dependency_overrides[get_edgar_controller] = lambda: fake_controller

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        resp = await client.get(
            "/v1/edgar/statements/restatements/ledger",
            params={
                "cik": "0000320193",
                "statement_type": "INCOME_STATEMENT",
                "fiscal_year": 2024,
                "fiscal_period": "FY",
            },
        )

    assert resp.status_code == 502
    body = resp.json()
    err = body["error"]
    assert err["code"] == "EDGAR_UPSTREAM_ERROR"
    assert err["http_status"] == 502
    assert err["message"] == "upstream failure"
    assert isinstance(err.get("details", {}), dict)
