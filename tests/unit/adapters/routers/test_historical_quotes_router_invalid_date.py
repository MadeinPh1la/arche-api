# tests/unit/routers/test_historical_quotes_router_invalid_date.py
# Copyright (c) Arche.
# SPDX-License-Identifier: MIT
from __future__ import annotations

from fastapi.testclient import TestClient

from arche_api.main import create_app


def test_router_returns_400_on_invalid_date_format():
    c = TestClient(create_app())
    r = c.get(
        "/v2/quotes/historical",
        params={
            "tickers": ["AAPL"],
            "from_": "not-a-date",
            "to": "2025-01-02",
            "interval": "1d",
            "page": 1,
            "page_size": 50,
        },
    )
    assert r.status_code == 400
    body = r.json()
    # Standard error envelope path (bypasses response_model)
    assert body.get("error", {}).get("code") == "VALIDATION_ERROR"
