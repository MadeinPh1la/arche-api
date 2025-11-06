from __future__ import annotations

import pytest
from httpx import AsyncClient


@pytest.mark.anyio
@pytest.mark.use_fake_uc  # use test UC to avoid touching real adapters
async def test_paginated_envelope_shape(app_client: AsyncClient):
    # minimal valid request that your fake UC supports
    params = {
        "tickers": "AAPL",
        "from_": "2025-01-01",
        "to": "2025-01-31",
        "interval": "1d",
        "page": 1,
        "page_size": 50,
    }
    resp = await app_client.get("/v1/quotes/historical", params=params)
    assert resp.status_code == 200, resp.text
    body = resp.json()
    # PaginatedEnvelope snapshot shows these top-level keys:
    assert set(body) == {"items", "page", "page_size", "total"}
    assert isinstance(body["items"], list)
    assert isinstance(body["page"], int) and body["page"] >= 1
    assert isinstance(body["page_size"], int) and 1 <= body["page_size"] <= 500
    assert isinstance(body["total"], int) and body["total"] >= 0


@pytest.mark.anyio
@pytest.mark.use_fake_uc
async def test_error_envelope_shape(app_client: AsyncClient):
    # Force a validation error: invalid page_size=0
    params = {
        "tickers": "AAPL",
        "from_": "2025-01-01",
        "to": "2025-01-31",
        "interval": "1d",
        "page": 1,
        "page_size": 0,  # invalid; minimum is 1
    }
    resp = await app_client.get("/v1/quotes/historical", params=params)
    assert resp.status_code in (400, 422), resp.text
    payload = resp.json()

    # ErrorEnvelope snapshot shows a single 'error' property,
    # with trace_id inside ErrorObject (not at the top level).
    assert set(payload) == {"error"} or set(payload) == {
        "error",
        "trace_id",
    }  # tolerate middleware variants
    error_obj = payload["error"]
    assert {"code", "http_status", "message"} <= set(error_obj)
    # If middleware injects trace_id inside the error object, validate it (optional)
    if "trace_id" in error_obj:
        assert isinstance(error_obj["trace_id"], (str, type(None)))
