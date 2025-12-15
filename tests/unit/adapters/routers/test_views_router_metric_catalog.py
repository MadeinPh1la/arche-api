# tests/unit/adapters/routers/test_views_router_metric_catalog.py
# Copyright (c)
# SPDX-License-Identifier: MIT
"""HTTP tests for metric views catalog and view-based time series.

Scope:
    - Validate happy-path behavior for GET /v1/views/metrics (catalog).
    - Validate that GET /v1/views/metrics/{bundle_code} sets the `view`
      metadata field on the derived time-series payload.
"""

from __future__ import annotations

from datetime import date

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from arche_api.adapters.routers.views_router import router as views_router
from arche_api.application.schemas.dto.edgar_derived import (
    EdgarDerivedMetricsPointDTO,
)
from arche_api.dependencies.edgar import get_edgar_controller
from arche_api.domain.enums.derived_metric import DerivedMetric
from arche_api.domain.enums.edgar import (
    AccountingStandard,
    FiscalPeriod,
    StatementType,
)


class _FakeEdgarControllerForViews:
    """Fake controller returning a single derived-metrics point for views tests."""

    async def get_derived_metrics_timeseries(  # noqa: D401 - simple fake
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
        """Return a single DTO, ignoring most inputs."""
        assert isinstance(ciks, list)
        assert isinstance(statement_type, StatementType)
        assert frequency in {"annual", "quarterly"}
        assert bundle_code is not None

        return [
            EdgarDerivedMetricsPointDTO(
                cik="0000000001",
                statement_type=StatementType.INCOME_STATEMENT,
                accounting_standard=AccountingStandard.US_GAAP,
                statement_date=date(2024, 12, 31),
                fiscal_year=2024,
                fiscal_period=FiscalPeriod.FY,
                currency="USD",
                metrics={DerivedMetric.GROSS_MARGIN: "0.400000"},
                normalized_payload_version_sequence=1,
            ),
        ]


@pytest.fixture()
def app() -> FastAPI:
    """FastAPI app instance including only the views router."""
    app = FastAPI()
    app.include_router(views_router)
    return app


def test_list_metric_views_catalog_happy_path(app: FastAPI) -> None:
    """GET /v1/views/metrics should return the catalog of metric views."""
    client = TestClient(app)

    resp = client.get("/v1/views/metrics")
    assert resp.status_code == 200, resp.text

    payload = resp.json()
    assert "data" in payload
    data = payload["data"]

    assert "views" in data
    views = data["views"]
    assert isinstance(views, list)
    assert len(views) >= 1

    # Catalog should contain the core_fundamentals view with at least GROSS_MARGIN.
    codes = [v["code"] for v in views]
    assert codes == sorted(codes)

    core_view = next(v for v in views if v["code"] == "core_fundamentals")
    assert "Core fundamentals" in core_view["label"]
    assert "metrics" in core_view
    assert "GROSS_MARGIN" in core_view["metrics"]


def test_get_metric_view_timeseries_sets_view_metadata(app: FastAPI) -> None:
    """View-based time series should populate the `view` field."""
    app.dependency_overrides[get_edgar_controller] = (  # type: ignore[assignment]
        lambda: _FakeEdgarControllerForViews()
    )

    client = TestClient(app)

    resp = client.get(
        "/v1/views/metrics/core_fundamentals",
        params={
            "ciks": ["0000000001"],
            "statement_type": "INCOME_STATEMENT",
            "frequency": "annual",
        },
    )

    assert resp.status_code == 200, resp.text

    payload = resp.json()
    assert "data" in payload
    data = payload["data"]

    # View metadata should be set to the bundle code.
    assert data["view"] == "core_fundamentals"

    # Points should be present and correctly shaped.
    points = data["points"]
    assert len(points) == 1
    point = points[0]
    assert point["cik"] == "0000000001"
    assert point["metrics"]["GROSS_MARGIN"] == "0.400000"
