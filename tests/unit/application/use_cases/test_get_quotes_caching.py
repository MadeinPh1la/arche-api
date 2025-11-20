# tests/unit/application/use_cases/test_get_quotes_caching.py
from __future__ import annotations

from datetime import UTC, datetime
from decimal import Decimal
from typing import Any

import pytest

from stacklion_api.application.use_cases.quotes.get_quotes import GetQuotes
from stacklion_api.domain.entities.quote import Quote
from stacklion_api.domain.interfaces.gateways.market_data_gateway import (
    MarketDataGatewayProtocol,
)
from stacklion_api.infrastructure.caching.json_cache import TTL_QUOTE_HOT_S


class RecordingCache:
    """Cache stub that tracks TTL and keys."""

    def __init__(self) -> None:
        self.data: dict[str, dict[str, Any]] = {}
        self.ttls: dict[str, int] = {}

    async def get_json(self, key: str):
        return self.data.get(key)

    async def set_json(self, key: str, value, ttl: int):
        self.data[key] = dict(value)
        self.ttls[key] = ttl


class RecordingGateway(MarketDataGatewayProtocol):
    """Gateway stub that records calls and returns simple quotes."""

    def __init__(self) -> None:
        self.calls: list[list[str]] = []

    async def get_latest_quotes(self, tickers):
        self.calls.append(list(tickers))
        now = datetime(2025, 1, 1, tzinfo=UTC)
        return [
            Quote(
                ticker=t.upper(),
                price=Decimal("123.45"),
                currency="USD",
                as_of=now,
                volume=100,
            )
            for t in tickers
        ]


@pytest.mark.asyncio
async def test_get_quotes_uses_cache_and_respects_ttl():
    cache = RecordingCache()
    gw = RecordingGateway()
    uc = GetQuotes(gateway=gw, cache=cache)

    tickers = ["aapl", "msft"]

    # First call: cache miss, gateway called once.
    batch1 = await uc.execute(tickers)
    assert len(batch1.items) == 2
    assert {"AAPL", "MSFT"} == {q.ticker for q in batch1.items}
    assert gw.calls == [["AAPL", "MSFT"]]

    # Cache should be populated with two keys.
    assert "quote:AAPL" in cache.data
    assert "quote:MSFT" in cache.data
    assert cache.ttls["quote:AAPL"] == TTL_QUOTE_HOT_S
    assert cache.ttls["quote:MSFT"] == TTL_QUOTE_HOT_S

    # Second call: same tickers, should hit cache and not call gateway again.
    batch2 = await uc.execute(tickers)
    assert len(batch2.items) == 2
    assert gw.calls == [["AAPL", "MSFT"]]
