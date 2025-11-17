# tests/integration/observability/test_metrics_historical_quotes.py
# Prometheus metrics smoke & assertions for A6.
# - Hits /v2/quotes/historical
# - Scrapes /metrics
# - Asserts histogram/counter lines exist post-request

from datetime import date

import httpx
import pytest
import respx
from fastapi import FastAPI
from fastapi.testclient import TestClient

from stacklion_api.main import create_app


@pytest.fixture(scope="module")
def app() -> FastAPI:
    """Create the FastAPI application once per test module."""
    return create_app()


@pytest.fixture(scope="module")
def client(app: FastAPI) -> TestClient:
    """HTTP client bound to the app under test."""
    return TestClient(app)


@respx.mock
def test_metrics_exposed_and_increment_after_success(client: TestClient) -> None:
    """Successful historical quotes request should emit core metrics."""
    # Mock upstream EOD call
    respx.get("https://api.marketstack.com/v2/eod").mock(
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
    r1 = client.get("/v2/quotes/historical", params=params)
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
def test_metrics_error_paths_increment_counters(client: TestClient) -> None:
    """Error path (upstream 429) should increment error metrics.

    We intentionally avoid asserting on specific label values or reason strings.
    The contract here is:
        - the stacklion_market_data_errors_total metric exists, and
        - at least one instance of that metric has a value >= 1 after the 429 path.
    """
    # Make upstream return 429 to trigger rate-limited path
    respx.get("https://api.marketstack.com/v2/intraday").mock(
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
    # We only care that the request exercises the error path; status code is
    # implementation-defined (may be 4xx or 5xx depending on mapping).
    client.get("/v2/quotes/historical", params=params)

    prom = client.get("/metrics")
    assert prom.status_code == 200
    body = prom.text

    # Error counter metric should be present.
    assert "stacklion_market_data_errors_total" in body

    # Extract all non-comment lines for the error counter, e.g.:
    # stacklion_market_data_errors_total{...labels...} 1.0
    lines = [
        line
        for line in body.splitlines()
        if line.startswith("stacklion_market_data_errors_total") and not line.startswith("#")
    ]
    assert lines, "Expected at least one stacklion_market_data_errors_total metric line"

    # Parse the numeric values from the metric lines and ensure at least one
    # reflects an increment (value >= 1.0).
    values = []
    for line in lines:
        parts = line.split()
        if len(parts) < 2:
            continue
        try:
            values.append(float(parts[-1]))
        except ValueError:
            continue

    assert values, "Could not parse any numeric values for stacklion_market_data_errors_total"
    assert any(v >= 1.0 for v in values), (
        "Expected stacklion_market_data_errors_total to be incremented "
        "after exercising the upstream 429 error path"
    )


@pytest.fixture(autouse=True)
def _configure_env_for_metrics(monkeypatch: pytest.MonkeyPatch) -> None:
    """Ensure DI chooses the real gateway + rate limiting for these metrics tests."""
    # Non-test environment so the app doesn't select stubs.
    monkeypatch.setenv("ENVIRONMENT", "dev")
    # Dummy non-empty key so the Marketstack client wiring is enabled.
    monkeypatch.setenv("MARKETSTACK_ACCESS_KEY", "x")
    # Ensure rate limiting is enabled so the 429 path actually gets exercised.
    monkeypatch.setenv("RATE_LIMIT_ENABLED", "true")
    # Make sure we are not in any "test mode" shortcut paths.
    monkeypatch.delenv("STACKLION_TEST_MODE", raising=False)
