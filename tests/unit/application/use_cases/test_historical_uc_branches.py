# tests/unit/application/use_cases/test_historical_uc_branches.py
# Copyright (c) Stacklion.
# SPDX-License-Identifier: MIT
from __future__ import annotations

import re
from datetime import UTC, datetime
from decimal import Decimal

import pytest

from stacklion_api.application.schemas.dto.quotes import HistoricalBarDTO, HistoricalQueryDTO
from stacklion_api.application.use_cases.quotes.get_historical_quotes import (
    GetHistoricalQuotesUseCase,
)
from stacklion_api.dependencies.market_data import InMemoryAsyncCache
from stacklion_api.domain.entities.historical_bar import BarInterval
from stacklion_api.domain.exceptions.market_data import MarketDataRateLimited


# ---------- helpers ----------
def _q() -> HistoricalQueryDTO:
    return HistoricalQueryDTO(
        tickers=["AAPL"],
        from_=datetime(2025, 1, 1, tzinfo=UTC),
        to=datetime(2025, 1, 2, tzinfo=UTC),
        interval=BarInterval.I1D,
        page=1,
        page_size=50,
    )


class _GatewayWithProviderETag:
    async def get_historical_bars(self, *args, **kwargs):
        dto = HistoricalBarDTO(
            ticker="AAPL",
            timestamp=datetime(2025, 1, 2, tzinfo=UTC),
            open=Decimal("1"),
            high=Decimal("2"),
            low=Decimal("0.5"),
            close=Decimal("1.5"),
            volume=Decimal("10"),
            interval=BarInterval.I1D,
        )
        return [dto], 1, 'W/"provided-etag"'


class _GatewayNoEtagDictReturn:
    async def get_historical_bars(self, *args, **kwargs):
        # dict return with items/total triggers the normalization path
        item = {
            "ticker": "AAPL",
            "timestamp": datetime(2025, 1, 2, tzinfo=UTC).isoformat(),
            "open": "1",
            "high": "2",
            "low": "0.5",
            "close": "1.5",
            "volume": "10",
            "interval": str(BarInterval.I1D),
        }
        return {"items": [item], "total": 1}  # no etag -> UC computes weak ETag


class _GatewayRaisesRateLimited:
    async def get_historical_bars(self, *args, **kwargs):
        raise MarketDataRateLimited("429")


# ---------- tests ----------
@pytest.mark.asyncio
async def test_uc_prefers_provider_etag_when_present():
    uc = GetHistoricalQuotesUseCase(cache=InMemoryAsyncCache(), gateway=_GatewayWithProviderETag())
    items, total, etag = await uc.execute(_q())
    assert total == 1 and etag == 'W/"provided-etag"'
    assert items[0].ticker == "AAPL"


@pytest.mark.asyncio
async def test_uc_computes_weak_etag_and_normalizes_dict_return():
    uc = GetHistoricalQuotesUseCase(cache=InMemoryAsyncCache(), gateway=_GatewayNoEtagDictReturn())
    items, total, etag = await uc.execute(_q())
    assert total == 1
    assert re.match(r'^W/"[0-9a-f]{64}"$', etag)


@pytest.mark.asyncio
async def test_uc_raises_and_records_on_rate_limited(monkeypatch):
    # We only assert that the UC re-raises; the counter/observation are validated in integration tests.
    uc = GetHistoricalQuotesUseCase(cache=InMemoryAsyncCache(), gateway=_GatewayRaisesRateLimited())
    with pytest.raises(MarketDataRateLimited):
        await uc.execute(_q())
