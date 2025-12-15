from __future__ import annotations

from datetime import date

from fastapi.testclient import TestClient

from arche_api.main import create_app


def test_historical_422_when_missing_tickers() -> None:
    app = create_app()
    client = TestClient(app)

    # omit 'tickers' entirely to trigger query-param validation
    params = {
        "from_": str(date(2025, 1, 1)),
        "to": str(date(2025, 1, 2)),
        "interval": "1d",
        "page": 1,
        "page_size": 50,
    }
    r = client.get("/v2/quotes/historical", params=params)
    assert r.status_code == 422  # FastAPI validation path
