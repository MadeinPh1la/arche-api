from datetime import date

import httpx
import respx
from fastapi.testclient import TestClient

from arche_api.main import create_app

PAYLOAD = {
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
}


@respx.mock
def test_historical_returns_304_on_matching_etag():
    """First GET returns 200 with ETag; second GET with If-None-Match returns 304."""
    # Mock Marketstack EOD twice with identical payload so ETag is stable
    respx.get("https://api.marketstack.com/v2/eod").mock(
        return_value=httpx.Response(200, json=PAYLOAD)
    )
    respx.get("https://api.marketstack.com/v2/eod").mock(
        return_value=httpx.Response(200, json=PAYLOAD)
    )

    app = create_app()
    client = TestClient(app)

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
    etag = r1.headers.get("ETag")
    assert etag, "Expected ETag on first response"

    # Send the same request with If-None-Match to trigger 304 path
    r2 = client.get("/v2/quotes/historical", params=params, headers={"If-None-Match": etag})
    assert r2.status_code == 304
    # 304 should not have a body; headers still applied by presenter
    assert r2.headers.get("ETag") == etag
