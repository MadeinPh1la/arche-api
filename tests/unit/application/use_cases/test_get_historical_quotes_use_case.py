from datetime import UTC, datetime
from decimal import Decimal

import pytest

from stacklion_api.application.schemas.dto.quotes import HistoricalBarDTO, HistoricalQueryDTO
from stacklion_api.application.use_cases.quotes.get_historical_quotes import (
    GetHistoricalQuotesUseCase,
)
from stacklion_api.domain.entities.historical_bar import BarInterval
from stacklion_api.domain.exceptions.market_data import MarketDataValidationError


class FakeCache:
    def __init__(self):
        self.store = {}

    async def get_json(self, key: str):
        return self.store.get(key)

    async def set_json(self, key: str, value, ttl: int):
        self.store[key] = value


class FakeGateway:
    def __init__(self):
        self.calls = 0

    async def get_historical_bars(self, q):
        self.calls += 1
        return [
            HistoricalBarDTO(
                ticker="AAPL",
                timestamp=datetime(2025, 1, 2, 0, 0, tzinfo=UTC),
                open=Decimal("1"),
                high=Decimal("2"),
                low=Decimal("0.5"),
                close=Decimal("1.5"),
                volume=Decimal("10"),
                interval=q.interval,
            )
        ], 1


@pytest.mark.asyncio
async def test_cache_miss_populates_and_returns_etag():
    uc = GetHistoricalQuotesUseCase(cache=FakeCache(), gateway=FakeGateway())
    q = HistoricalQueryDTO(
        tickers=["AAPL"],
        from_=datetime(2025, 1, 1, tzinfo=UTC),
        to=datetime(2025, 1, 2, tzinfo=UTC),
        interval=BarInterval.I1D,
        page=1,
        page_size=50,
    )
    items, total, etag = await uc.execute(q)
    assert total == 1 and items[0].ticker == "AAPL"
    assert etag.startswith('W/"')


@pytest.mark.asyncio
async def test_cache_hit_skips_gateway():
    cache = FakeCache()
    uc = GetHistoricalQuotesUseCase(cache=cache, gateway=FakeGateway())
    q = HistoricalQueryDTO(
        tickers=["AAPL"],
        from_=datetime(2025, 1, 1, tzinfo=UTC),
        to=datetime(2025, 1, 2, tzinfo=UTC),
        interval=BarInterval.I1D,
        page=1,
        page_size=50,
    )
    # first call populates cache
    items, total, etag = await uc.execute(q)
    # second call hits cache
    items2, total2, etag2 = await uc.execute(q)
    assert (items2, total2, etag2) == (items, total, etag)


@pytest.mark.asyncio
async def test_from_after_to_raises():
    uc = GetHistoricalQuotesUseCase(cache=FakeCache(), gateway=FakeGateway())
    q = HistoricalQueryDTO(
        tickers=["AAPL"],
        from_=datetime(2025, 1, 3, tzinfo=UTC),
        to=datetime(2025, 1, 2, tzinfo=UTC),
        interval=BarInterval.I1D,
        page=1,
        page_size=50,
    )
    with pytest.raises(MarketDataValidationError):
        await uc.execute(q)
