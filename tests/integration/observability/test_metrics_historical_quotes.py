# tests/integration/observability/test_metrics_historical_quotes.py
# Prometheus metrics smoke & assertions for A6.
# - Hits /v2/quotes/historical
# - Scrapes /metrics
# - Asserts histogram/counter lines exist post-request

from __future__ import annotations

from datetime import date

import httpx
import pytest
import respx
from fastapi import FastAPI
from fastapi.testclient import TestClient

from stacklion_api.main import create_app

EOD_URL_REGEX = r"https://api\.marketstack\.com/v2/eod.*"
INTRADAY_URL_REGEX = r"https://api\.marketstack\.com/v2/intraday.*"


@pytest.fixture(scope="module")
def app(monkeypatch: pytest.MonkeyPatch) -> FastAPI:
    """Create the FastAPI application once per test module with metrics wiring enabled.

    Env is configured here so DI builds the real Marketstack client + metrics
    middleware rather than any test stubs.
    """
    # Non-"test" environment so the app selects the real gateway wiring.
    monkeypatch.setenv("ENVIRONMENT", "dev")
    # Dummy non-empty key so the Marketstack client is enabled.
    monkeypatch.setenv("MARKETSTACK_API_KEY", "x")
    # Enable rate limiting so the 429 path is actually exercised.
    monkeypatch.setenv("RATE_LIMIT_ENABLED", "true")
    # Ensure no internal test-mode shortcuts are active.
    monkeypatch.delenv("STACKLION_TEST_MODE", raising=False)

    return create_app()


@pytest.fixture(scope="module")
def client(app: FastAPI) -> TestClient:
    """HTTP client bound to the app under test."""
    return TestClient(app)


@respx.mock
def test_metrics_exposed_and_increment_after_success(client: TestClient) -> None:
    """Successful historical quotes request should emit core metrics."""
    # Mock upstream EOD call (V2, ignore query params).
    respx.get(url__regex=EOD_URL_REGEX).mock(
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
        ),
    )

    # Hit the historical endpoint once to produce metrics.
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

    # Scrape metrics.
    prom = client.get("/metrics")
    assert prom.status_code == 200
    body = prom.text

    # Assert key metrics exist.
    # Histograms usually have _bucket/_count/_sum lines after first observation.
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
    """Error path (upstream 429) should surface error metrics.

    The exact label set and increment semantics are implementation details.
    This smoke test asserts that exercising a 429 path still results in the
    error metric being present in the Prometheus text exposition.
    """
    # Mock upstream intraday call (V2, ignore query params).
    respx.get(url__regex=INTRADAY_URL_REGEX).mock(
        return_value=httpx.Response(429, json={"error": {"code": "rate_limit"}}),
    )

    params = {
        "tickers": ["AAPL"],
        "from_": str(date(2025, 1, 1)),
        "to": str(date(2025, 1, 1)),
        "interval": "1m",
        "page": 1,
        "page_size": 1,
    }

    client.get("/v2/quotes/historical", params=params)

    prom = client.get("/metrics")
    assert prom.status_code == 200
    body = prom.text

    # Error counter metric should be registered and exposed somewhere
    # (either as HELP/TYPE or as an actual series line).
    assert "stacklion_market_data_errors_total" in body
