# Prometheus metrics smoke & assertions for A6.
# - Hits /v1/quotes/historical
# - Scrapes /metrics
# - Asserts histogram/counter lines exist post-request

from datetime import date

import httpx
import pytest
import respx
from fastapi import FastAPI
from fastapi.testclient import TestClient

# Your app factory that registers metrics endpoint and the A6 router
from stacklion_api.main import create_app


@pytest.fixture(scope="module")
def app() -> FastAPI:
    return create_app()


@pytest.fixture(scope="module")
def client(app) -> TestClient:
    return TestClient(app)


@respx.mock
def test_metrics_exposed_and_increment_after_success(client: TestClient):
    # Mock upstream EOD call
    respx.get("https://api.marketstack.com/v1/eod").mock(
        return_value=httpx.Response(
            200,
            json={
                "pagination": {"limit": 50, "offset": 0, "count": 1, "total": 1},
                "data": [
                    {
                        "symbol": "AAPL",
                        "date": "2025-01-02T00:00:00Z",
                        "open": 1,
                        "high": 2,
                        "low": 0.5,
                        "close": 1.5,
                        "volume": 10,
                    }
                ],
            },
        )
    )

    # Hit the historical endpoint once to produce metrics
    params = {
        "tickers": ["AAPL"],
        "from_": str(date(2025, 1, 1)),
        "to": str(date(2025, 1, 2)),
        "interval": "1d",
        "page": 1,
        "page_size": 50,
    }
    r1 = client.get("/v1/quotes/historical", params=params)
    assert r1.status_code == 200

    # Scrape metrics
    prom = client.get("/metrics")
    assert prom.status_code == 200
    body = prom.text

    # Assert key metrics exist (rename if your project uses different names)
    # Histograms usually have _count/_sum/_bucket lines after first observation.
    assert "stacklion_market_data_gateway_latency_seconds_bucket" in body
    assert "stacklion_market_data_gateway_latency_seconds_count" in body
    assert "stacklion_usecase_historical_quotes_latency_seconds_count" in body
    # Cache either hit or miss; at least one counter should show up.
    assert (
        "stacklion_market_data_cache_hits_total" in body
        or "stacklion_market_data_cache_misses_total" in body
    )


@respx.mock
def test_metrics_error_paths_increment_counters(client: TestClient):
    # Make upstream return 429 to trigger rate-limited path
    respx.get("https://api.marketstack.com/v1/intraday").mock(
        return_value=httpx.Response(429, json={"error": {"code": "rate_limit"}})
    )

    params = {
        "tickers": ["AAPL"],
        "from_": str(date(2025, 1, 1)),
        "to": str(date(2025, 1, 1)),
        "interval": "1m",
        "page": 1,
        "page_size": 1,
    }
    client.get("/v1/quotes/historical", params=params)

    prom = client.get("/metrics")
    assert prom.status_code == 200
    body = prom.text

    # Error counters should reflect at least one error; label names may differ.
    # Adjust label filters to your actual implementation (e.g., reason="rate_limited").
    assert "stacklion_market_data_errors_total" in body
    assert 'reason="rate_limited"' in body or "rate_limited" in body
