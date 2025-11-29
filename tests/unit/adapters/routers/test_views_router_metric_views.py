# tests/unit/adapters/routers/test_views_router_metric_views.py
# Copyright (c)
# SPDX-License-Identifier: MIT
"""HTTP tests for metric views (bundles) derived-metrics endpoint.

Scope:
    - Validate happy-path behavior for
      GET /v1/views/metrics/{bundle_code}.
    - Ensure request validation and error mapping behave as expected.
    - Assert that the router + presenter wiring shape the HTTP envelope
      correctly from controller DTOs.
    - Verify that controller-level bundle validation (unknown bundle,
      bundle+metrics) is mapped to 400 VALIDATION_ERROR.
"""

from __future__ import annotations

from datetime import date

import pytest
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient

from stacklion_api.adapters.controllers.edgar_controller import EdgarController
from stacklion_api.adapters.routers.views_router import router as views_router
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


class _NoopUseCase:
    """Use-case stub that should never be invoked in these tests."""

    async def execute(self, *args, **kwargs):  # noqa: D401
        """Raise if accidentally called."""
        raise RuntimeError("Unexpected use-case execution in views router tests.")


class _FakeDerivedMetricsUseCase:
    """Fake use-case returning a preconfigured series of derived metrics points."""

    def __init__(self, points: list[EdgarDerivedMetricsPointDTO]) -> None:
        self._points = points

    async def execute(self, req) -> list[EdgarDerivedMetricsPointDTO]:  # noqa: D401
        """Return the preconfigured DTO list."""
        # Basic sanity checks on the request object.
        assert hasattr(req, "ciks")
        assert isinstance(req.ciks, list)
        assert req.frequency in {"annual", "quarterly"}
        return self._points


@pytest.fixture
def app() -> FastAPI:
    """FastAPI app instance including only the Metric Views router."""
    app = FastAPI()
    app.include_router(views_router)
    return app


@pytest.mark.anyio
async def test_get_metric_view_timeseries_happy_path(app: FastAPI) -> None:
    """Happy path: endpoint returns a success envelope with sorted points."""
    dto = _make_point(
        cik="0000320193",
        statement_date=date(2023, 12, 31),
        fiscal_year=2023,
        fiscal_period=FiscalPeriod.FY,
        normalized_payload_version_sequence=1,
    )

    controller = EdgarController(
        list_filings_uc=_NoopUseCase(),
        get_filing_uc=_NoopUseCase(),
        list_statements_uc=_NoopUseCase(),
        get_filing_statements_uc=_NoopUseCase(),
        get_derived_metrics_timeseries_uc=_FakeDerivedMetricsUseCase(points=[dto]),
    )
    app.dependency_overrides[get_edgar_controller] = lambda: controller

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        resp = await client.get(
            "/v1/views/metrics/core_fundamentals",
            params={
                "ciks": ["0000320193"],
                "statement_type": "INCOME_STATEMENT",
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
async def test_get_metric_view_timeseries_unknown_bundle_returns_400(
    app: FastAPI,
) -> None:
    """Unknown bundle should return 400 VALIDATION_ERROR."""
    controller = EdgarController(
        list_filings_uc=_NoopUseCase(),
        get_filing_uc=_NoopUseCase(),
        list_statements_uc=_NoopUseCase(),
        get_filing_statements_uc=_NoopUseCase(),
        get_derived_metrics_timeseries_uc=_FakeDerivedMetricsUseCase(points=[]),
    )
    app.dependency_overrides[get_edgar_controller] = lambda: controller

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        resp = await client.get(
            "/v1/views/metrics/does_not_exist",
            params={
                "ciks": ["0000320193"],
                "statement_type": "INCOME_STATEMENT",
                "frequency": "annual",
            },
        )

    assert resp.status_code == 400
    body = resp.json()
    assert "error" in body
    err = body["error"]
    assert err["code"] == "VALIDATION_ERROR"
    assert err["http_status"] == 400
    # Message should include the domain error from expand_view_metrics.
    assert "Unknown metric view" in err["message"]


@pytest.mark.anyio
async def test_get_metric_view_timeseries_bundle_with_explicit_metrics_returns_400(
    app: FastAPI,
) -> None:
    """Providing bundle_code and explicit metrics together should return 400."""
    controller = EdgarController(
        list_filings_uc=_NoopUseCase(),
        get_filing_uc=_NoopUseCase(),
        list_statements_uc=_NoopUseCase(),
        get_filing_statements_uc=_NoopUseCase(),
        get_derived_metrics_timeseries_uc=_FakeDerivedMetricsUseCase(points=[]),
    )
    app.dependency_overrides[get_edgar_controller] = lambda: controller

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        resp = await client.get(
            "/v1/views/metrics/core_fundamentals",
            params={
                "ciks": ["0000320193"],
                "statement_type": "INCOME_STATEMENT",
                "frequency": "annual",
                "metrics": ["GROSS_MARGIN"],
            },
        )

    assert resp.status_code == 400
    body = resp.json()
    assert "error" in body
    err = body["error"]
    assert err["code"] == "VALIDATION_ERROR"
    assert err["http_status"] == 400
    assert "bundle_code and metrics cannot both be provided" in err["message"]


@pytest.mark.anyio
async def test_get_metric_view_timeseries_edgar_mapping_error(
    app: FastAPI,
) -> None:
    """EdgarMappingError from the controller should be mapped to a 500 envelope."""

    class _MappingErrorController:
        async def get_derived_metrics_timeseries(  # noqa: D401
            self,
            *,
            ciks,
            statement_type,
            metrics,
            frequency,
            from_date,
            to_date,
            bundle_code=None,
        ) -> list[EdgarDerivedMetricsPointDTO]:
            """Always raise EdgarMappingError."""
            raise EdgarMappingError("bad window", details={"bundle_code": bundle_code})

    app.dependency_overrides[get_edgar_controller] = (  # type: ignore[assignment]
        lambda: _MappingErrorController()
    )

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        resp = await client.get(
            "/v1/views/metrics/core_fundamentals",
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
    assert isinstance(err.get("details", {}), dict)


@pytest.mark.anyio
async def test_get_metric_view_timeseries_edgar_upstream_error(
    app: FastAPI,
) -> None:
    """EdgarIngestionError should be mapped to a 502 envelope."""

    class _UpstreamErrorController:
        async def get_derived_metrics_timeseries(  # noqa: D401
            self,
            *,
            ciks,
            statement_type,
            metrics,
            frequency,
            from_date,
            to_date,
            bundle_code=None,
        ) -> list[EdgarDerivedMetricsPointDTO]:
            """Always raise EdgarIngestionError."""
            raise EdgarIngestionError("upstream failure", details={"upstream": "edgar"})

    app.dependency_overrides[get_edgar_controller] = (  # type: ignore[assignment]
        lambda: _UpstreamErrorController()
    )

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        resp = await client.get(
            "/v1/views/metrics/core_fundamentals",
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
