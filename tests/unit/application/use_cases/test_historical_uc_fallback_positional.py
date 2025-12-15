# Copyright (c) Arche.
# SPDX-License-Identifier: MIT
from __future__ import annotations

import re
from datetime import UTC, datetime
from decimal import Decimal

import pytest

from arche_api.application.schemas.dto.quotes import HistoricalBarDTO, HistoricalQueryDTO
from arche_api.application.use_cases.quotes.get_historical_quotes import (
    GetHistoricalQuotesUseCase,
)
from arche_api.dependencies.market_data import InMemoryAsyncCache
from arche_api.domain.entities.historical_bar import BarInterval


class _PositionalGateway:
    async def get_historical_bars(self, tickers, date_from, date_to, interval, limit, offset):
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
        # return 2-tuple to cover that branch
        return [dto], 1


@pytest.mark.asyncio
async def test_uc_fallbacks_to_positional_signature_and_computes_weak_etag():
    uc = GetHistoricalQuotesUseCase(cache=InMemoryAsyncCache(), gateway=_PositionalGateway())
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
    assert re.match(r'^W/"[0-9a-f]{64}"$', etag)
