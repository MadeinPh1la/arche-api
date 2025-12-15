# tests/integration/http/test_fundamentals_timeseries_endpoint.py
# Copyright (c)
# SPDX-License-Identifier: MIT
"""HTTP-level tests for the fundamentals time-series endpoint.

These tests validate that the /v1/fundamentals/time-series endpoint:

    * Propagates the `use_tier1_only` flag into the application use case.
    * Returns a metrics mapping keyed by Tier-1 canonical metric codes when
      `use_tier1_only=true` and no explicit metrics are provided.
"""

from __future__ import annotations

from datetime import date
from decimal import Decimal
from typing import Any

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from arche_api.adapters.routers.fundamentals_router import (
    get_uow,
)
from arche_api.adapters.routers.fundamentals_router import (
    router as fundamentals_router,
)
from arche_api.application.use_cases.statements.get_fundamentals_timeseries import (
    GetFundamentalsTimeSeriesRequest,
    GetFundamentalsTimeSeriesUseCase,
)
from arche_api.domain.entities.edgar_fundamentals_timeseries import (
    FundamentalsTimeSeriesPoint,
)
from arche_api.domain.enums.edgar import (
    AccountingStandard,
    FiscalPeriod,
    StatementType,
)
from arche_api.domain.services.canonical_metric_registry import (
    get_tier1_metrics_for_statement_type,
)


class _DummyUoW:
    """Minimal async context manager stub for UnitOfWork."""

    async def __aenter__(self) -> _DummyUoW:  # pragma: no cover - trivial
        return self

    async def __aexit__(self, exc_type, exc, tb) -> None:  # pragma: no cover - trivial
        return None


@pytest.fixture(name="client")
def _client(monkeypatch: pytest.MonkeyPatch) -> TestClient:
    """FastAPI TestClient with fundamentals router wired and UoW overridden."""
    app = FastAPI()
    app.include_router(fundamentals_router)

    # Override the EDGAR UoW dependency so the handler can construct the use case.
    app.dependency_overrides[get_uow] = lambda: _DummyUoW()

    # Patch the fundamentals use case execute method so we don't hit real infra.
    async def _fake_execute(
        self: GetFundamentalsTimeSeriesUseCase,
        req: GetFundamentalsTimeSeriesRequest,
    ) -> list[FundamentalsTimeSeriesPoint]:
        # Assert that the HTTP layer propagated the Tier-1 toggle correctly.
        assert req.use_tier1_only is True
        assert req.metrics is None

        statement_type = req.statement_type
        tier1_metrics = get_tier1_metrics_for_statement_type(statement_type)

        metrics = {metric: Decimal("1.0") for metric in tier1_metrics}

        point = FundamentalsTimeSeriesPoint(
            cik="0000320193",
            statement_type=statement_type,
            accounting_standard=AccountingStandard.US_GAAP,
            statement_date=date(2024, 9, 28),
            fiscal_year=2024,
            fiscal_period=FiscalPeriod.FY,
            currency="USD",
            metrics=metrics,
            normalized_payload_version_sequence=1,
        )

        return [point]

    monkeypatch.setattr(
        GetFundamentalsTimeSeriesUseCase,
        "execute",
        _fake_execute,
        raising=True,
    )

    return TestClient(app)


def test_fundamentals_timeseries_tier1_metrics_flow_through_http(client: TestClient) -> None:
    """Tier-1 canonical metrics should appear as HTTP metric keys.

    When `use_tier1_only=true` and no explicit `metrics` are provided, the
    endpoint should return a metrics mapping whose keys include the Tier-1
    canonical metric codes for the requested statement_type.
    """
    params: dict[str, Any] = {
        "ciks": ["0000320193"],
        "statement_type": "INCOME_STATEMENT",
        "frequency": "annual",
        "use_tier1_only": True,
        "from": "2020-01-01",
        "to": "2024-12-31",
        "page": 1,
        "page_size": 50,
    }

    response = client.get("/v1/fundamentals/time-series", params=params)
    assert response.status_code == 200, response.text

    payload = response.json()
    assert payload.get("items"), "Expected at least one fundamentals point in response"

    first_point = payload["items"][0]
    metrics = first_point.get("metrics", {})
    assert isinstance(metrics, dict)
    assert metrics, "Expected metrics mapping to be non-empty"

    # Compute expected Tier-1 codes from the registry for income statements.
    tier1_metrics = get_tier1_metrics_for_statement_type(StatementType.INCOME_STATEMENT)
    expected_codes = {metric.value for metric in tier1_metrics}

    metric_keys = set(metrics.keys())

    # All Tier-1 codes should be present in the HTTP metrics mapping.
    missing = expected_codes - metric_keys
    assert not missing, f"Missing Tier-1 metrics in HTTP payload: {sorted(missing)}"

    # Values should be decimal strings.
    for code in expected_codes:
        value = metrics[code]
        assert isinstance(value, str)
        assert value == "1.0"
