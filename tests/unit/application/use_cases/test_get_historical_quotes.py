# tests/unit/application/use_cases/test_get_historical_quotes_use_case.py
from __future__ import annotations

import asyncio
from datetime import UTC, datetime
from decimal import Decimal

import pytest

from arche_api.application.schemas.dto.quotes import HistoricalBarDTO, HistoricalQueryDTO
from arche_api.application.use_cases.quotes.get_historical_quotes import (
    GetHistoricalQuotesUseCase,
)
from arche_api.domain.entities.historical_bar import BarInterval
from arche_api.domain.exceptions.market_data import MarketDataValidationError


class FakeCache:
    def __init__(self):
        self.store = {}

    async def get_json(self, key: str):
        return self.store.get(key)

    async def set_json(self, key: str, value, ttl: int):
        self.store[key] = value


class StubGateway:
    def __init__(self, items, total):
        self.items = items
        self.total = total
        self.calls = 0

    async def get_historical_bars(self, q):
        self.calls += 1
        await asyncio.sleep(0)
        return self.items, self.total


def _bar(interval=BarInterval.I1D) -> HistoricalBarDTO:
    return HistoricalBarDTO(
        ticker="AAPL",
        timestamp=datetime(2025, 1, 2, tzinfo=UTC),
        open=Decimal("1"),
        high=Decimal("2"),
        low=Decimal("0.5"),
        close=Decimal("1.5"),
        volume=Decimal("10"),
        interval=interval,
    )


def _q(interval=BarInterval.I1D) -> HistoricalQueryDTO:
    return HistoricalQueryDTO(
        tickers=["AAPL"],
        from_=datetime(2025, 1, 1, tzinfo=UTC),
        to=datetime(2025, 1, 2, tzinfo=UTC),
        interval=interval,
        page=1,
        page_size=50,
    )


@pytest.mark.asyncio
async def test_cache_miss_sets_cache_and_returns_etag():
    cache = FakeCache()
    gw = StubGateway([_bar()], 1)
    uc = GetHistoricalQuotesUseCase(cache=cache, gateway=gw)

    items, total, etag = await uc.execute(_q())
    assert total == 1 and items[0].ticker == "AAPL"
    assert etag.startswith('W/"')
    assert gw.calls == 1
    assert cache.store  # wrote to cache


@pytest.mark.asyncio
async def test_cache_hit_skips_gateway_and_respects_if_none_match():
    cache = FakeCache()
    gw = StubGateway([_bar()], 1)
    uc = GetHistoricalQuotesUseCase(cache=cache, gateway=gw)

    items, total, etag = await uc.execute(_q())
    gw.calls = 0  # reset
    # If-None-Match matches -> short-circuit (controller will 304)
    items2, total2, etag2 = await uc.execute(_q(), if_none_match=etag)
    assert (items2, total2, etag2) == (items, total, etag)
    assert gw.calls == 0


@pytest.mark.asyncio
async def test_invalid_window_raises():
    cache = FakeCache()
    gw = StubGateway([_bar()], 1)
    uc = GetHistoricalQuotesUseCase(cache=cache, gateway=gw)

    bad = HistoricalQueryDTO(
        tickers=["AAPL"],
        from_=datetime(2025, 1, 3, tzinfo=UTC),
        to=datetime(2025, 1, 2, tzinfo=UTC),
        interval=BarInterval.I1D,
        page=1,
        page_size=50,
    )
    with pytest.raises(MarketDataValidationError):
        await uc.execute(bad)
