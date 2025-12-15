# tests/unit/application/use_cases/test_historical_uc_key_and_ttl.py
from __future__ import annotations

from datetime import UTC, datetime

import pytest

from arche_api.application.schemas.dto.quotes import HistoricalBarDTO, HistoricalQueryDTO
from arche_api.application.use_cases.quotes.get_historical_quotes import (
    GetHistoricalQuotesUseCase,
)
from arche_api.domain.entities.historical_bar import BarInterval
from arche_api.infrastructure.caching.json_cache import TTL_EOD_S, TTL_INTRADAY_RECENT_S


class RecordingCache:
    """Cache stub that records writes."""

    def __init__(self) -> None:
        self.last_key: str | None = None
        self.last_ttl: int | None = None
        self.stored: dict[str, dict] = {}

    async def get_json(self, key: str):
        return None

    async def set_json(self, key: str, value, ttl: int):
        self.last_key = key
        self.last_ttl = ttl
        self.stored[key] = value


class SimpleGateway:
    """Gateway that returns a single bar, to exercise key/TTL logic."""

    def __init__(self, interval: BarInterval) -> None:
        self._interval = interval

    async def get_historical_bars(self, *args, **kwargs):
        q = kwargs.get("q")
        if q is None and args:
            # DTO-style call
            q = args[0]
        ticker = q.tickers[0]
        dto = HistoricalBarDTO(
            ticker=ticker,
            timestamp=datetime(2025, 1, 1, tzinfo=UTC),
            open=1,
            high=2,
            low=0.5,
            close=1.5,
            volume=10,
            interval=self._interval,
        )
        return [dto], 1, None


@pytest.mark.asyncio
async def test_historical_uc_builds_canonical_key_and_uses_eod_ttl():
    cache = RecordingCache()
    gw = SimpleGateway(interval=BarInterval.I1D)
    uc = GetHistoricalQuotesUseCase(cache=cache, gateway=gw)

    q = HistoricalQueryDTO(
        tickers=["MSFT", "AAPL"],
        from_=datetime(2025, 1, 1, tzinfo=UTC),
        to=datetime(2025, 1, 2, tzinfo=UTC),
        interval=BarInterval.I1D,
        page=1,
        page_size=100,
    )

    await uc.execute(q)

    assert cache.last_key is not None
    assert cache.last_ttl == TTL_EOD_S

    # Key shape: historical:{tickers_sorted}:{interval_value}:{from_iso}:{to_iso}:p1:s100
    expected_prefix = "historical:AAPL,MSFT:"
    assert cache.last_key.startswith(expected_prefix)
    assert ":p1:s100" in cache.last_key


@pytest.mark.asyncio
async def test_historical_uc_uses_intraday_ttl_for_intraday_interval():
    cache = RecordingCache()
    gw = SimpleGateway(interval=BarInterval.I1MIN)
    uc = GetHistoricalQuotesUseCase(cache=cache, gateway=gw)

    q = HistoricalQueryDTO(
        tickers=["AAPL"],
        from_=datetime(2025, 1, 1, tzinfo=UTC),
        to=datetime(2025, 1, 1, tzinfo=UTC),
        interval=BarInterval.I1MIN,
        page=1,
        page_size=100,
    )

    await uc.execute(q)

    assert cache.last_ttl == TTL_INTRADAY_RECENT_S
