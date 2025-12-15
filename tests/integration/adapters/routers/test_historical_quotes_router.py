# tests/integration/routers/test_historical_quotes_router.py
# Copyright (c) Arche.
# SPDX-License-Identifier: MIT
"""Integration tests: Historical Quotes Router (A6).

Synopsis:
    Verifies the HTTP surface at `/v2/quotes/historical` for:
      * 200 success with weak ETag
      * 304 Not Modified when `If-None-Match` matches

Design:
    - Hermetic: overrides the router's dependency `get_historical_quotes_use_case`
      so no outbound HTTP occurs and responses are deterministic.
    - Uses a small `FakeUC` that returns one OHLCV bar and a stable ETag.
"""

from __future__ import annotations

from datetime import UTC, datetime
from decimal import Decimal

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from arche_api.adapters.routers.historical_quotes_router import (
    router as historical_quotes_router,
)
from arche_api.application.schemas.dto.quotes import HistoricalBarDTO
from arche_api.dependencies.market_data import get_historical_quotes_use_case
from arche_api.domain.entities.historical_bar import BarInterval


class FakeUC:
    """Deterministic use-case stub for hermetic router tests."""

    def __init__(self, etag: str = 'W/"abc123"') -> None:
        """Initialize the stub.

        Args:
            etag: Weak ETag to return on success (defaults to ``W/"abc123"``).
        """
        self.calls = 0
        self.etag = etag

    async def execute(self, q, if_none_match: str | None = None):
        """Return one synthetic OHLCV bar and the configured ETag.

        Args:
            q: Historical query DTO (ignored; shape compatibility only).
            if_none_match: Conditional request token (ignored in this stub).

        Returns:
            (items, total, etag): list[HistoricalBarDTO], int, str
        """
        self.calls += 1
        items = [
            HistoricalBarDTO(
                ticker="AAPL",
                timestamp=datetime(2025, 1, 2, tzinfo=UTC),
                open=Decimal("1"),
                high=Decimal("2"),
                low=Decimal("0.5"),
                close=Decimal("1.5"),
                volume=Decimal("10"),
                interval=BarInterval.I1D,
            )
        ]
        return items, 1, self.etag


@pytest.fixture
def app() -> FastAPI:
    """FastAPI app with DI override for the historical quotes UC.

    Returns:
        A FastAPI instance with the historical quotes router mounted and the
        `get_historical_quotes_use_case` dependency overridden to use `FakeUC`.
    """
    fast = FastAPI()

    def _override_uc() -> FakeUC:
        return FakeUC()

    # Ensure router uses our deterministic UC (no outbound HTTP).
    fast.dependency_overrides[get_historical_quotes_use_case] = _override_uc

    fast.include_router(historical_quotes_router)

    try:
        yield fast
    finally:
        # Prevent DI leakage into other tests
        fast.dependency_overrides.clear()


def test_200_success_and_etag_header(app: FastAPI) -> None:
    """200: returns PaginatedEnvelope with weak ETag on success."""
    c = TestClient(app)
    r = c.get(
        "/v2/quotes/historical",
        params={
            "tickers": ["AAPL"],
            "from_": "2025-01-01",
            "to": "2025-01-02",
            "interval": "1d",
            "page": 1,
            "page_size": 50,
        },
    )
    assert r.status_code == 200
    assert r.headers.get("ETag") == 'W/"abc123"'
    body = r.json()
    # Router returns canonical PaginatedEnvelope (items at top level)
    assert "items" in body and isinstance(body["items"], list)


def test_304_when_if_none_match_matches(app: FastAPI) -> None:
    """304: when If-None-Match matches the UC-provided ETag."""
    c = TestClient(app)
    r = c.get(
        "/v2/quotes/historical",
        params={
            "tickers": ["AAPL"],
            "from_": "2025-01-01",
            "to": "2025-01-02",
            "interval": "1d",
            "page": 1,
            "page_size": 50,
        },
        headers={"If-None-Match": 'W/"abc123"'},
    )
    assert r.status_code == 304
