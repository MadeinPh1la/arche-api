# tests/integration/edgar/test_e6_restatement_delta.py
# Copyright (c)
# SPDX-License-Identifier: MIT
"""Integration tests for /v1/fundamentals/restatement-delta (E6).

Scope:
    - Validation of version sequence ordering.
    - Error envelope mapping for validation failures.
    - Skeleton for happy-path coverage once EDGAR data is available.
"""

from __future__ import annotations

from typing import Any

import pytest
from fastapi.testclient import TestClient


@pytest.mark.integration
def test_restatement_delta_validation_from_ge_to(
    client: TestClient,
) -> None:
    """from_version_sequence >= to_version_sequence yields 400 VALIDATION_ERROR."""
    params: dict[str, Any] = {
        "cik": "0000320193",
        "statement_type": "INCOME_STATEMENT",
        "fiscal_year": 2024,
        "fiscal_period": "FY",
        "from_version_sequence": 3,
        "to_version_sequence": 3,
    }

    response = client.get("/v1/fundamentals/restatement-delta", params=params)

    assert response.status_code == 400
    payload = response.json()
    assert "error" in payload, payload
    error = payload["error"]
    assert error["code"] == "VALIDATION_ERROR"
    assert error["http_status"] == 400
    assert error["message"] == "from_version_sequence must be < to_version_sequence."
    assert "trace_id" in error
    assert error["details"] == {
        "from_version_sequence": 3,
        "to_version_sequence": 3,
    }


@pytest.mark.integration
@pytest.mark.skip(reason="Requires two distinct EDGAR versions for the same statement identity.")
def test_restatement_delta_happy_path_metrics_and_shape(
    client: TestClient,
) -> None:
    """Happy path: restatement delta returns per-metric changes.

    Once wired with real data, expectations are:

        * 200 OK
        * SuccessEnvelope with `data` shaped as RestatementDeltaHTTP
        * metrics: mapping of canonical codes to metric-delta objects

    The underlying seed data should ensure that at least one metric actually
    changes between from_version_sequence and to_version_sequence so that:
        - len(data.metrics) >= 1
        - each metric entry has 'metric', 'old', 'new', 'diff' fields.
    """
    params: dict[str, Any] = {
        "cik": "0000320193",
        "statement_type": "INCOME_STATEMENT",
        "fiscal_year": 2022,
        "fiscal_period": "FY",
        "from_version_sequence": 1,
        "to_version_sequence": 2,
    }

    response = client.get("/v1/fundamentals/restatement-delta", params=params)

    assert response.status_code == 200
    payload = response.json()

    # SuccessEnvelope shape
    assert set(payload.keys()) == {"data"}
    data = payload["data"]

    # RestatementDeltaHTTP invariants
    for key in (
        "cik",
        "statement_type",
        "accounting_standard",
        "statement_date",
        "fiscal_year",
        "fiscal_period",
        "currency",
        "from_version_sequence",
        "to_version_sequence",
        "metrics",
    ):
        assert key in data

    metrics = data["metrics"]
    assert isinstance(metrics, dict)
    assert metrics, "expected at least one changed metric"

    sample_delta = next(iter(metrics.values()))
    for key in ("metric", "old", "new", "diff"):
        assert key in sample_delta
