from __future__ import annotations

from datetime import date

from fastapi.testclient import TestClient

from stacklion_api.main import create_app


def test_historical_400_when_from_after_to() -> None:
    app = create_app()
    client = TestClient(app)

    params = {
        "tickers": ["AAPL"],
        "from_": str(date(2025, 1, 3)),  # later than 'to'
        "to": str(date(2025, 1, 1)),
        "interval": "1d",
        "page": 1,
        "page_size": 50,
    }
    r = client.get("/v2/quotes/historical", params=params)
    # The use-case raises MarketDataValidationError; router maps to 400 VALIDATION_ERROR
    assert r.status_code == 400
    body = r.json()
    assert "error" in body
