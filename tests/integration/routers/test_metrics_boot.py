from __future__ import annotations

import pytest
from httpx import AsyncClient


@pytest.mark.anyio
async def test_metrics_endpoint_exposes_histograms(http_client: AsyncClient) -> None:
    r = await http_client.get("/metrics")
    assert r.status_code == 200
    text = r.text
    # Request latency and readiness histograms should exist
    assert "http_server_request_duration_seconds_bucket" in text
    assert "readyz_db_latency_seconds_bucket" in text
