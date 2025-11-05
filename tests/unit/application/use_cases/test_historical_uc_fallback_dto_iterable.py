# tests/unit/application/use_cases/test_historical_uc_fallback_dto_iterable.py
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


class _LegacyDtoGatewayIterable:
    async def get_historical_bars(self, q: HistoricalQueryDTO):
        # return iterable (list) to hit that normalization branch
        return [
            HistoricalBarDTO(
                ticker=q.tickers[0],
                timestamp=datetime(2025, 1, 2, tzinfo=UTC),
                open=Decimal("1"),
                high=Decimal("2"),
                low=Decimal("0.5"),
                close=Decimal("1.5"),
                volume=Decimal("10"),
                interval=q.interval,
            )
        ]


@pytest.mark.asyncio
async def test_uc_fallbacks_to_legacy_dto_and_normalizes_iterable():
    uc = GetHistoricalQuotesUseCase(cache=InMemoryAsyncCache(), gateway=_LegacyDtoGatewayIterable())
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
