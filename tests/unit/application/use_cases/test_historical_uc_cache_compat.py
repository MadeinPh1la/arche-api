# tests/unit/application/use_cases/test_historical_uc_cache_compat.py
from __future__ import annotations

from datetime import UTC, datetime
from decimal import Decimal

import pytest

from arche_api.application.schemas.dto.quotes import HistoricalBarDTO, HistoricalQueryDTO
from arche_api.application.use_cases.quotes.get_historical_quotes import (
    GetHistoricalQuotesUseCase,
)
from arche_api.domain.entities.historical_bar import BarInterval


class PositionalOnlyCase:
    """Cache stub that only accepts positional ttl to hit UC fallback branch."""

    def __init__(self) -> None:
        self.stored: dict[str, dict] = {}

    async def get_json(self, key: str):
        return self.stored.get(key)

    async def set_json(self, key: str, value, ttl: int):
        # Note: no ttl kwarg in signature on purpose.
        self.stored[key] = value


class DictGateway:
    """Gateway used to exercise cache fallback; returns DTOs directly."""

    async def get_historical_bars(self, q: HistoricalQueryDTO):
        dto = HistoricalBarDTO(
            ticker=q.tickers[0],
            timestamp=datetime(2025, 1, 2, tzinfo=UTC),
            open=Decimal("1"),
            high=Decimal("2"),
            low=Decimal("0.5"),
            close=Decimal("1.5"),
            volume=Decimal("10"),
            interval=q.interval,
        )
        # Return shape compatible with UC: (items, total, etag)
        return [dto], 1, None


@pytest.mark.asyncio
async def test_uc_cache_fallback_to_positional_ttl_signature():
    """Exercise _cache_set_json_compat fallback when cache.set_json doesn't accept ttl= kwarg."""
    cache = PositionalOnlyCase()
    gw = DictGateway()
    uc = GetHistoricalQuotesUseCase(cache=cache, gateway=gw)

    q = HistoricalQueryDTO(
        tickers=["AAPL"],
        from_=datetime(2025, 1, 1, tzinfo=UTC),
        to=datetime(2025, 1, 2, tzinfo=UTC),
        interval=BarInterval.I1D,
        page=1,
        page_size=50,
    )

    items, total, etag = await uc.execute(q)
    assert total == 1
    assert isinstance(items[0], HistoricalBarDTO)
    assert items[0].ticker == "AAPL"
    assert etag.startswith('W/"')
    # ensure cache was written via positional ttl path
    assert cache.stored
