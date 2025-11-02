from datetime import date

import httpx
import pytest
import respx
from fastapi import FastAPI
from fastapi.testclient import TestClient

# import your DI wiring that registers the router with controller/presenter/usecase/gw/cache
from stacklion_api.main import create_app


@pytest.fixture(scope="module")
def app() -> FastAPI:
    return create_app()


@pytest.fixture(scope="module")
def client(app) -> TestClient:
    return TestClient(app)


@pytest.mark.parametrize("interval", ["1d"])
@respx.mock
def test_list_historical_and_304_etag(client, interval):
    # Mock upstream call used by gateway
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

    params = {
        "tickers": ["AAPL"],
        "from_": str(date(2025, 1, 1)),
        "to": str(date(2025, 1, 2)),
        "interval": interval,
        "page": 1,
        "page_size": 50,
    }
    r1 = client.get("/v1/quotes/historical", params=params)
    assert r1.status_code == 200
    etag = r1.headers.get("ETag")
    assert etag

    # Second request with If-None-Match → 304
    r2 = client.get("/v1/quotes/historical", params=params, headers={"If-None-Match": etag})
    assert r2.status_code == 304
    assert r2.headers.get("ETag") == etag
