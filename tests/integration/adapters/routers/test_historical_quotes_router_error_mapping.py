# tests/integration/routers/test_historical_quotes_router_error_mapping.py
# Copyright (c) Arche.
# SPDX-License-Identifier: MIT
from __future__ import annotations

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from arche_api.adapters.routers.historical_quotes_router import (
    router as historical_quotes_router,
)
from arche_api.dependencies.market_data import get_historical_quotes_use_case
from arche_api.domain.exceptions.market_data import (
    MarketDataBadRequest,
    MarketDataQuotaExceeded,
    MarketDataRateLimited,
    MarketDataUnavailable,
)


class _RaisingUC:
    """Fake UC that raises a configured domain exception from execute()."""

    def __init__(self, exc: Exception) -> None:
        self.exc = exc

    async def execute(self, q, if_none_match=None):
        raise self.exc


def _app_with_uc(uc) -> FastAPI:
    fast = FastAPI()
    fast.dependency_overrides[get_historical_quotes_use_case] = lambda: uc
    fast.include_router(historical_quotes_router)
    return fast


def _params() -> dict:
    return {
        "tickers": ["AAPL"],
        "from_": "2025-01-01",
        "to": "2025-01-02",
        "interval": "1d",
        "page": 1,
        "page_size": 50,
    }


@pytest.mark.parametrize(
    "exc, expected_status, expected_code",
    [
        (MarketDataRateLimited("burst"), 429, "RATE_LIMITED"),
        (MarketDataQuotaExceeded("quota"), 402, "PROVIDER_QUOTA_EXCEEDED"),
        (MarketDataBadRequest("shape"), 400, "UPSTREAM_SCHEMA_ERROR"),
        (MarketDataUnavailable("down"), 503, "MARKET_DATA_UNAVAILABLE"),
    ],
)
def test_router_error_mapping(exc: Exception, expected_status: int, expected_code: str) -> None:
    app = _app_with_uc(_RaisingUC(exc))
    c = TestClient(app)
    r = c.get("/v2/quotes/historical", params=_params())
    assert r.status_code == expected_status
    assert r.json()["error"]["code"] == expected_code
