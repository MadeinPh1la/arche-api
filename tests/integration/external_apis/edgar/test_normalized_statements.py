# tests/integration/edgar/test_e6_normalized_statements.py
# Copyright (c)
# SPDX-License-Identifier: MIT
"""Integration tests for /v1/fundamentals/normalized-statements (E6).

Scope:
    - Basic validation around CIK format and parameters.
    - Error envelope mapping for not-found cases (once wired).
    - Skeleton for happy-path coverage.
"""

from __future__ import annotations

from typing import Any

import pytest
from fastapi.testclient import TestClient


@pytest.mark.integration
@pytest.mark.skip(reason="Decide whether to envelope CIK validation or keep FastAPI default.")
def test_normalized_statement_invalid_cik_yields_400(client: TestClient) -> None:
    """Invalid CIK should yield 400; exact body depends on HTTPException handling.

    NOTE:
        Currently, CIK normalization uses HTTPException, which may bypass the
        canonical ErrorEnvelope handler. This test is intentionally skipped
        until you decide whether to refactor CIK validation to use
        ErrorEnvelope or keep FastAPI's default error payload.
    """
    params: dict[str, Any] = {
        "cik": "NOT_A_CIK",
        "statement_type": "INCOME_STATEMENT",
        "fiscal_year": 2024,
        "fiscal_period": "FY",
    }

    response = client.get("/v1/fundamentals/normalized-statements", params=params)

    assert response.status_code == 400


@pytest.mark.integration
@pytest.mark.skip(reason="Requires EDGAR statement data and GetNormalizedStatementUseCase wiring.")
def test_normalized_statement_happy_path_includes_latest_and_history(
    client: TestClient,
) -> None:
    """Happy path: latest normalized statement with optional version history.

    Expectations once wired:
        * 200 OK
        * SuccessEnvelope with `data` holding NormalizedStatementViewHTTP:
            - data.latest: EdgarStatementVersionHTTP-compatible shape
            - data.version_history: list[...] ordered ascending by version_sequence
    """
    params = {
        "cik": "0000320193",
        "statement_type": "INCOME_STATEMENT",
        "fiscal_year": 2024,
        "fiscal_period": "FY",
        "include_version_history": True,
    }

    response = client.get("/v1/fundamentals/normalized-statements", params=params)

    assert response.status_code == 200
    payload = response.json()

    # SuccessEnvelope shape
    assert set(payload.keys()) == {"data"}
    view = payload["data"]

    assert "latest" in view
    assert "version_history" in view

    latest = view["latest"]
    history = view["version_history"]

    # Minimal shape checks for EdgarStatementVersionHTTP-style objects
    for key in (
        "accession_id",
        "cik",
        "statement_type",
        "accounting_standard",
        "statement_date",
        "fiscal_year",
        "fiscal_period",
        "currency",
        "version_sequence",
        "filing_type",
        "filing_date",
    ):
        assert key in latest

    assert isinstance(history, list)
    if history:
        # Version history should be ordered ascending by version_sequence
        seqs = [item["version_sequence"] for item in history]
        assert seqs == sorted(seqs)
