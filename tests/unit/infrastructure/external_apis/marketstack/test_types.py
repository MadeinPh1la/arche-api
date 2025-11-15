from __future__ import annotations

from stacklion_api.infrastructure.external_apis.marketstack.types import (
    MarketstackLatestItem,
    MarketstackLatestResponse,
)


def test_marketstack_latest_item_typed_dict_usage() -> None:
    item: MarketstackLatestItem = {
        "symbol": "AAPL",
        "last": "123.45",
        "date": "2025-01-01T10:00:00+00:00",
        "currency": "USD",
        "volume": 1_000_000,
    }

    assert item["symbol"] == "AAPL"
    assert item["last"] == "123.45"
    assert item["date"].startswith("2025-01-01T10:00")
    assert item["currency"] == "USD"
    assert item["volume"] == 1_000_000


def test_marketstack_latest_response_shape() -> None:
    response: MarketstackLatestResponse = {
        "data": [
            {
                "symbol": "MSFT",
                "last": 100.5,
                "date": "2025-01-01T11:00:00+00:00",
            }
        ]
    }

    assert "data" in response
    assert len(response["data"]) == 1

    item = response["data"][0]
    assert item["symbol"] == "MSFT"
    assert item["last"] == 100.5
    assert item["date"].startswith("2025-01-01T11:00")
