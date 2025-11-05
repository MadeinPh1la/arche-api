import json
from datetime import UTC, datetime
from pathlib import Path

import httpx
import pytest
import respx

from stacklion_api.adapters.gateways.marketstack_gateway import MarketstackGateway
from stacklion_api.application.schemas.dto.quotes import HistoricalQueryDTO
from stacklion_api.domain.entities.historical_bar import BarInterval
from stacklion_api.domain.exceptions.market_data import (
    MarketDataRateLimited,
    MarketDataValidationError,
)
from stacklion_api.infrastructure.external_apis.marketstack.settings import MarketstackSettings


def _load_payload():
    return json.loads(Path("tests/data/marketstack_eod.json").read_text())


@pytest.fixture
def settings():
    return MarketstackSettings(
        base_url="https://api.marketstack.com/v1", access_key="test", timeout_s=2.0, max_retries=0
    )


@pytest.mark.asyncio
@respx.mock
async def test_eod_happy_path(settings, tmp_path):
    payload = _load_payload()
    route = respx.get("https://api.marketstack.com/v1/eod").mock(
        return_value=httpx.Response(200, json=payload)
    )

    async with httpx.AsyncClient() as client:
        gw = MarketstackGateway(client, settings)
        q = HistoricalQueryDTO(
            tickers=["AAPL"],
            interval=BarInterval.I1D,
            from_=datetime(2025, 1, 1, tzinfo=UTC),
            to=datetime(2025, 1, 2, tzinfo=UTC),
            page=1,
            page_size=2,
        )
        items, total = await gw.get_historical_bars(q)
        assert route.called
        assert total == payload["pagination"]["total"]
        assert items and items[0].ticker == "AAPL"


@pytest.mark.asyncio
@respx.mock
async def test_intraday_rate_limited_raises(settings):
    respx.get("https://api.marketstack.com/v1/intraday").mock(
        return_value=httpx.Response(429, json={"error": {"code": "rate_limit"}})
    )
    async with httpx.AsyncClient() as client:
        gw = MarketstackGateway(client, settings)
        q = HistoricalQueryDTO(
            tickers=["AAPL"],
            interval=BarInterval.I1M,
            from_=datetime(2025, 1, 1, tzinfo=UTC),
            to=datetime(2025, 1, 1, tzinfo=UTC),
            page=1,
            page_size=1,
        )
        with pytest.raises(MarketDataRateLimited):
            await gw.get_historical_bars(q)


@pytest.mark.asyncio
@respx.mock
async def test_bad_shape_raises_validation(settings):
    respx.get("https://api.marketstack.com/v1/eod").mock(
        return_value=httpx.Response(200, json={"nope": []})
    )
    async with httpx.AsyncClient() as client:
        gw = MarketstackGateway(client, settings)
        q = HistoricalQueryDTO(
            tickers=["AAPL"],
            interval=BarInterval.I1D,
            from_=datetime(2025, 1, 1, tzinfo=UTC),
            to=datetime(2025, 1, 1, tzinfo=UTC),
            page=1,
            page_size=1,
        )
        with pytest.raises(MarketDataValidationError):
            await gw.get_historical_bars(q)
