# tests/unit/adapters/routers/test_edgar_router_derived_timeseries.py
# Copyright (c)
# SPDX-License-Identifier: MIT
"""HTTP tests for EDGAR derived-metrics time-series endpoint.

Scope:
    - Validate happy-path behavior for GET /v1/edgar/derived-metrics/time-series.
    - Ensure request validation and error mapping behave as expected.
    - Assert that the router + presenter wiring shape the HTTP envelope
      correctly from controller DTOs.
"""

from __future__ import annotations

from datetime import date

import pytest
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient

from stacklion_api.adapters.routers.edgar_router import router as edgar_router
from stacklion_api.application.schemas.dto.edgar_derived import (
    EdgarDerivedMetricsPointDTO,
)
from stacklion_api.dependencies.edgar import get_edgar_controller
from stacklion_api.domain.enums.derived_metric import DerivedMetric
from stacklion_api.domain.enums.edgar import (
    AccountingStandard,
    FiscalPeriod,
    StatementType,
)
from stacklion_api.domain.exceptions.edgar import (
    EdgarIngestionError,
    EdgarMappingError,
)


@pytest.fixture
def app() -> FastAPI:
    """FastAPI app instance including only the EDGAR router."""
    app = FastAPI()
    app.include_router(edgar_router)
    return app


class _FakeDerivedMetricsController:
    """Fake controller returning a fixed series for derived metrics."""

    def __init__(self, points: list[EdgarDerivedMetricsPointDTO]) -> None:
        self._points = points

    async def get_derived_metrics_timeseries(  # noqa: D401 - simple fake
        self,
        *,
        ciks,
        statement_type,
        metrics,
        frequency,
        from_date,
        to_date,
    ) -> list[EdgarDerivedMetricsPointDTO]:
        """Return the preconfigured DTO list, ignoring inputs."""
        # Basic sanity check: router passes through the expected types.
        assert isinstance(ciks, list)
        assert isinstance(statement_type, StatementType)
        assert frequency in {"annual", "quarterly"}
        # from_date / to_date may be None, validated in use-case.
        return self._points


class _FakeErrorController:
    """Fake controller that always raises a specific EDGAR exception."""

    def __init__(self, exc: Exception) -> None:
        self._exc = exc

    async def get_derived_metrics_timeseries(
        self,
        *,
        ciks,
        statement_type,
        metrics,
        frequency,
        from_date,
        to_date,
    ) -> list[EdgarDerivedMetricsPointDTO]:
        raise self._exc


def _make_point(
    *,
    cik: str = "0000320193",
    statement_type: StatementType = StatementType.INCOME_STATEMENT,
    accounting_standard: AccountingStandard = AccountingStandard.US_GAAP,
    statement_date: date = date(2023, 12, 31),
    fiscal_year: int = 2023,
    fiscal_period: FiscalPeriod = FiscalPeriod.FY,
    currency: str = "USD",
    metrics: dict[DerivedMetric, str] | None = None,
    normalized_payload_version_sequence: int = 1,
) -> EdgarDerivedMetricsPointDTO:
    """Helper to build a minimal but valid derived-metrics DTO."""
    return EdgarDerivedMetricsPointDTO(
        cik=cik,
        statement_type=statement_type,
        accounting_standard=accounting_standard,
        statement_date=statement_date,
        fiscal_year=fiscal_year,
        fiscal_period=fiscal_period,
        currency=currency,
        metrics=metrics
        or {
            DerivedMetric.GROSS_MARGIN: "0.4",
            DerivedMetric.NET_MARGIN: "0.2",
        },
        normalized_payload_version_sequence=normalized_payload_version_sequence,
    )


@pytest.mark.anyio
async def test_get_derived_metrics_timeseries_happy_path(app: FastAPI) -> None:
    """Happy path: endpoint returns a success envelope with sorted points."""
    # Arrange: single point DTO from fake controller
    dto = _make_point(
        cik="0000320193",
        statement_date=date(2023, 12, 31),
        fiscal_year=2023,
        fiscal_period=FiscalPeriod.FY,
        normalized_payload_version_sequence=1,
    )
    fake_controller = _FakeDerivedMetricsController(points=[dto])

    app.dependency_overrides[get_edgar_controller] = lambda: fake_controller

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        resp = await client.get(
            "/v1/edgar/derived-metrics/time-series",
            params={
                "ciks": ["0000320193"],
                "statement_type": "INCOME_STATEMENT",
                "metrics": ["GROSS_MARGIN", "NET_MARGIN"],
                "frequency": "annual",
                "from_date": "2023-01-01",
                "to_date": "2024-12-31",
            },
        )

    assert resp.status_code == 200
    payload = resp.json()

    # Envelope shape
    assert "data" in payload
    data = payload["data"]

    # Top-level metadata coming from presenter
    assert data["ciks"] == ["0000320193"]
    assert data["statement_type"] == "INCOME_STATEMENT"
    assert data["frequency"] == "annual"
    assert data["from_date"] == "2023-01-01"
    assert data["to_date"] == "2024-12-31"

    # Points collection
    points = data["points"]
    assert len(points) == 1

    point = points[0]
    assert point["cik"] == "0000320193"
    assert point["statement_type"] == "INCOME_STATEMENT"
    assert point["fiscal_year"] == 2023
    assert point["fiscal_period"] == "FY"
    assert point["currency"] == "USD"
    # Metrics are keyed by derived metric code and values are strings on the wire.
    assert point["metrics"]["GROSS_MARGIN"] == "0.4"
    assert point["metrics"]["NET_MARGIN"] == "0.2"


@pytest.mark.anyio
async def test_get_derived_metrics_timeseries_invalid_statement_type(
    app: FastAPI,
) -> None:
    """Invalid statement_type should return 400 with a validation error envelope."""
    fake_controller = _FakeDerivedMetricsController(points=[])
    app.dependency_overrides[get_edgar_controller] = lambda: fake_controller

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        resp = await client.get(
            "/v1/edgar/derived-metrics/time-series",
            params={
                "ciks": ["0000320193"],
                "statement_type": "NOT_A_STATEMENT_TYPE",
                "frequency": "annual",
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
async def test_get_derived_metrics_timeseries_invalid_frequency(
    app: FastAPI,
) -> None:
    """Invalid frequency should return 400 with a validation error envelope."""
    fake_controller = _FakeDerivedMetricsController(points=[])
    app.dependency_overrides[get_edgar_controller] = lambda: fake_controller

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        resp = await client.get(
            "/v1/edgar/derived-metrics/time-series",
            params={
                "ciks": ["0000320193"],
                "statement_type": "INCOME_STATEMENT",
                "frequency": "monthly",  # invalid
            },
        )

    assert resp.status_code == 400
    body = resp.json()
    assert "error" in body
    err = body["error"]
    assert err["code"] == "VALIDATION_ERROR"
    assert err["http_status"] == 400
    assert err["details"]["frequency"] == "monthly"


@pytest.mark.anyio
async def test_get_derived_metrics_timeseries_edgar_mapping_error(
    app: FastAPI,
) -> None:
    """EdgarMappingError from the controller should be mapped to a 500 envelope."""
    fake_controller = _FakeErrorController(
        EdgarMappingError("bad window", details={"from_date": "2025-01-01"}),
    )
    app.dependency_overrides[get_edgar_controller] = lambda: fake_controller

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        resp = await client.get(
            "/v1/edgar/derived-metrics/time-series",
            params={
                "ciks": ["0000320193"],
                "statement_type": "INCOME_STATEMENT",
                "frequency": "annual",
            },
        )

    assert resp.status_code == 500
    body = resp.json()
    assert "error" in body
    err = body["error"]
    assert err["code"] == "EDGAR_MAPPING_ERROR"
    assert err["http_status"] == 500
    assert err["message"] == "bad window"
    # Details may or may not be present depending on exception wiring; assert key if provided.
    assert isinstance(err.get("details", {}), dict)


@pytest.mark.anyio
async def test_get_derived_metrics_timeseries_edgar_upstream_error(
    app: FastAPI,
) -> None:
    """EdgarIngestionError should be mapped to a 502 envelope."""
    fake_controller = _FakeErrorController(
        EdgarIngestionError("upstream failure", details={"upstream": "edgar"}),
    )
    app.dependency_overrides[get_edgar_controller] = lambda: fake_controller

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        resp = await client.get(
            "/v1/edgar/derived-metrics/time-series",
            params={
                "ciks": ["0000320193"],
                "statement_type": "INCOME_STATEMENT",
                "frequency": "annual",
            },
        )

    assert resp.status_code == 502
    body = resp.json()
    assert "error" in body
    err = body["error"]
    assert err["code"] == "EDGAR_UPSTREAM_ERROR"
    assert err["http_status"] == 502
    assert err["message"] == "upstream failure"
    assert isinstance(err.get("details", {}), dict)


@pytest.mark.anyio
async def test_get_derived_metrics_timeseries_view_metadata_absent_for_edgar_endpoint(
    app: FastAPI,
) -> None:
    """Base EDGAR endpoint should not set a metric view (view should be null/absent)."""
    dto = _make_point(
        cik="0000000001",
        statement_date=date(2024, 12, 31),
        fiscal_year=2024,
        fiscal_period=FiscalPeriod.FY,
        normalized_payload_version_sequence=1,
    )
    fake_controller = _FakeDerivedMetricsController(points=[dto])
    app.dependency_overrides[get_edgar_controller] = lambda: fake_controller

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        resp = await client.get(
            "/v1/edgar/derived-metrics/time-series",
            params={
                "ciks": ["0000000001"],
                "statement_type": "INCOME_STATEMENT",
                "frequency": "annual",
            },
        )

    assert resp.status_code == 200
    payload = resp.json()
    assert "data" in payload
    data = payload["data"]

    # For the raw EDGAR endpoint, view should not be set to a bundle.
    assert data.get("view") is None
