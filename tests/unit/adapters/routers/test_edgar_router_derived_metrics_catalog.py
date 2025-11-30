# tests/unit/adapters/routers/test_edgar_router_derived_metrics_catalog.py
# Copyright (c)
# SPDX-License-Identifier: MIT
"""HTTP tests for EDGAR derived-metrics catalog endpoint.

Scope:
    - Validate happy-path behavior for GET /v1/edgar/derived-metrics/catalog.
    - Ensure schema integrity of catalog entries.
    - Ensure defensive error mapping behaves as expected.
"""

from __future__ import annotations

import pytest
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient

from stacklion_api.adapters.routers.edgar_router import router as edgar_router
from stacklion_api.domain.enums.derived_metric import DerivedMetric


@pytest.fixture
def app() -> FastAPI:
    """FastAPI app instance including only the EDGAR router."""
    app = FastAPI()
    app.include_router(edgar_router)
    return app


@pytest.mark.anyio
async def test_get_derived_metrics_catalog_happy_path(app: FastAPI) -> None:
    """Happy path: endpoint returns a success envelope with sorted metrics."""
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        resp = await client.get("/v1/edgar/derived-metrics/catalog")

    assert resp.status_code == 200
    payload = resp.json()

    # Envelope shape
    assert "data" in payload
    data = payload["data"]

    assert "metrics" in data
    metrics = data["metrics"]
    assert isinstance(metrics, list)
    assert metrics, "metrics list should not be empty"

    # Deterministic ordering by code.
    codes = [m["code"] for m in metrics]
    assert codes == sorted(codes)

    # Ensure some known metrics are present.
    expected_codes = {
        DerivedMetric.GROSS_MARGIN.value,
        DerivedMetric.REVENUE_GROWTH_TTM.value,
        DerivedMetric.ROIC.value,
    }
    assert expected_codes.issubset(set(codes))


@pytest.mark.anyio
async def test_get_derived_metrics_catalog_schema_integrity(app: FastAPI) -> None:
    """Each metric entry should expose the required schema fields."""
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        resp = await client.get("/v1/edgar/derived-metrics/catalog")

    assert resp.status_code == 200
    payload = resp.json()
    metrics = payload["data"]["metrics"]

    required_keys = {
        "code",
        "category",
        "description",
        "is_experimental",
        "required_statement_types",
        "required_inputs",
        "uses_history",
        "window_requirements",
    }

    for metric in metrics:
        # All required keys must be present.
        assert required_keys.issubset(metric.keys())
        # Types for complex fields.
        assert isinstance(metric["required_statement_types"], list)
        assert isinstance(metric["required_inputs"], list)
        assert isinstance(metric["window_requirements"], dict)


class _FaultyPresenter:
    """Presenter stub that forces an unhandled error."""

    def present_derived_metrics_catalog(self, *, specs, trace_id=None):  # noqa: D401, ANN001
        """Always raise to simulate an unhandled presenter error."""
        raise RuntimeError("boom")


@pytest.mark.anyio
async def test_get_derived_metrics_catalog_unhandled_error_maps_to_503(
    app: FastAPI,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Unhandled errors should be mapped to EDGAR_UNAVAILABLE 503 envelope."""
    # Monkeypatch the module-level presenter used by the router.

    # Re-import to ensure we patch the same instance used by FastAPI routing.
    from stacklion_api.adapters.routers import edgar_router as edgar_router_module

    monkeypatch.setattr(edgar_router_module, "presenter", _FaultyPresenter())

    # Need an app that includes the patched router.
    app = FastAPI()
    app.include_router(edgar_router_module.router)

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        resp = await client.get("/v1/edgar/derived-metrics/catalog")

    assert resp.status_code == 503
    body = resp.json()
    assert "error" in body
    err = body["error"]
    assert err["code"] == "EDGAR_UNAVAILABLE"
    assert err["http_status"] == 503
