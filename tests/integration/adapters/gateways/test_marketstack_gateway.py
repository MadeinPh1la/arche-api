# tests/unit/adapters/gateways/test_marketstack_gateway.py
from __future__ import annotations

from datetime import UTC, datetime
from decimal import Decimal

import pytest

from stacklion_api.adapters.gateways.marketstack_gateway import MarketstackGateway
from stacklion_api.application.schemas.dto.quotes import HistoricalQueryDTO
from stacklion_api.domain.entities.historical_bar import BarInterval
from stacklion_api.domain.exceptions.market_data import MarketDataValidationError


class StubClient:
    def __init__(self, raw, etag='W/"stub"'):
        self._raw = raw
        self._etag = etag
        self.calls = []

    async def eod(self, **kwargs):
        self.calls.append(("eod", kwargs))
        return self._raw, self._etag

    async def intraday(self, **kwargs):
        self.calls.append(("intraday", kwargs))
        return self._raw, self._etag


def _q(interval: BarInterval) -> HistoricalQueryDTO:
    return HistoricalQueryDTO(
        tickers=["aapl"],
        from_=datetime(2025, 1, 1, tzinfo=UTC),
        to=datetime(2025, 1, 2, tzinfo=UTC),
        interval=interval,
        page=1,
        page_size=50,
    )


@pytest.mark.parametrize("interval,ep", [(BarInterval.I1D, "eod"), (BarInterval.I5M, "intraday")])
@pytest.mark.asyncio
async def test_maps_rows_to_dtos_and_total(interval, ep):
    raw = {
        "data": [
            {
                "symbol": "aapl",
                "date": "2025-01-01T21:00:00Z",
                "open": "1",
                "high": "2",
                "low": "0.5",
                "close": "1.5",
                "volume": "10",
            }
        ],
        "pagination": {"total": 1},
    }
    gw = MarketstackGateway(client=StubClient(raw))
    items, total = await gw.get_historical_bars(_q(interval))
    assert total == 1
    assert len(items) == 1
    i = items[0]
    assert i.ticker == "AAPL"
    assert i.close == Decimal("1.5")
    assert i.interval == interval
    assert i.timestamp.tzinfo is not None


@pytest.mark.asyncio
async def test_bad_shape_raises_validation_error():
    gw = MarketstackGateway(client=StubClient({"unexpected": True}))
    with pytest.raises(MarketDataValidationError):
        await gw.get_historical_bars(_q(BarInterval.I1D))
