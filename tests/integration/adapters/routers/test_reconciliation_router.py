from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

# Adjust to your actual app factory import.
from arche_api.main import app  # noqa: F401


@pytest.fixture()
def client():
    return TestClient(app)


def test_reconciliation_run_validation_error(client: TestClient):
    r = client.post(
        "/v1/edgar/reconciliation/run",
        json={
            "cik": "",
            "statement_type": "BALANCE_SHEET",
            "fiscal_year": 2024,
            "fiscal_period": "FY",
            "deep": False,
            "fiscal_year_window": 0,
        },
    )
    assert r.status_code in (400, 422)


def test_reconciliation_summary_validation(client: TestClient):
    r = client.get(
        "/v1/edgar/reconciliation/summary",
        params={
            "cik": "0000320193",
            "statement_type": "BALANCE_SHEET",
            "fiscal_year_from": 2025,
            "fiscal_year_to": 2024,
            "limit": 10,
        },
    )
    assert r.status_code == 400
