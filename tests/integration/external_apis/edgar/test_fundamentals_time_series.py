# tests/integration/edgar/test_e6_fundamentals_time_series.py
# Copyright (c)
# SPDX-License-Identifier: MIT
"""Integration tests for /v1/fundamentals/time-series (E6).

Scope:
    - Validation behavior (date window).
    - Error envelope shape and codes.
    - Skeleton for happy-path coverage (to be wired to real seed data).

Notes:
    - These tests assume a FastAPI TestClient fixture named `client` is
      provided by tests/conftest.py.
"""

from __future__ import annotations

from typing import Any

import pytest
from fastapi.testclient import TestClient


@pytest.mark.integration
def test_time_series_validation_from_after_to(client: TestClient) -> None:
    """from > to must return 400 VALIDATION_ERROR with ErrorEnvelope."""
    params: dict[str, Any] = {
        "ciks": ["0000320193"],
        "statement_type": "INCOME_STATEMENT",
        "frequency": "annual",
        "from": "2024-01-02",
        "to": "2024-01-01",
    }

    response = client.get("/v1/fundamentals/time-series", params=params)

    assert response.status_code == 400
    payload = response.json()
    assert "error" in payload, payload
    error = payload["error"]
    assert error["code"] == "VALIDATION_ERROR"
    assert error["http_status"] == 400
    assert error["message"] == "from date must be <= to date."
    assert "trace_id" in error


@pytest.mark.integration
@pytest.mark.skip(reason="Requires EDGAR fundamentals seed data to be wired.")
def test_time_series_happy_path_single_cik_annual(
    client: TestClient,
) -> None:
    """Happy path: single CIK, annual frequency, basic envelope invariants.

    This test is intentionally skipped until EDGAR fundamentals seed data is
    available. When wiring, ensure that:

        * At least one INCOME_STATEMENT normalized payload exists for the
          given CIK within the date range.
        * The underlying use case returns deterministic ordering.

    Expected behavior:
        - 200 OK
        - PaginatedEnvelope with items >= 1
        - Each item is FundamentalsTimeSeriesPointHTTP-shaped.
    """
    params = {
        "ciks": ["0000320193"],
        "statement_type": "INCOME_STATEMENT",
        "frequency": "annual",
        "from": "2020-01-01",
        "to": "2024-12-31",
        "page": 1,
        "page_size": 50,
    }

    response = client.get("/v1/fundamentals/time-series", params=params)

    assert response.status_code == 200
    payload = response.json()

    # PaginatedEnvelope shape
    assert set(payload.keys()) == {"page", "page_size", "total", "items"}
    assert payload["page"] == 1
    assert payload["page_size"] == 50
    assert isinstance(payload["total"], int)
    assert isinstance(payload["items"], list)
    assert payload["total"] >= 1
    assert len(payload["items"]) >= 1

    point = payload["items"][0]
    # FundamentalsTimeSeriesPointHTTP invariants
    for key in (
        "cik",
        "statement_type",
        "accounting_standard",
        "statement_date",
        "fiscal_year",
        "fiscal_period",
        "currency",
        "metrics",
        "normalized_payload_version_sequence",
    ):
        assert key in point
