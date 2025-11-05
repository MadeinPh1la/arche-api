# tests/integration/adapters/gateways/test_marketstack_gateway_integration.py
from __future__ import annotations

from datetime import UTC, datetime

import httpx
import pytest
import respx

from stacklion_api.adapters.gateways.marketstack_gateway import MarketstackGateway
from stacklion_api.application.schemas.dto.quotes import HistoricalQueryDTO
from stacklion_api.domain.entities.historical_bar import BarInterval
from stacklion_api.domain.exceptions.market_data import (
    MarketDataRateLimited,
    MarketDataUnavailable,
)
from stacklion_api.infrastructure.external_apis.marketstack.client import MarketstackClient
from stacklion_api.infrastructure.external_apis.marketstack.settings import MarketstackSettings


@pytest.mark.asyncio
@respx.mock
async def test_gateway_429_rate_limited() -> None:
    cfg = MarketstackSettings(base_url="https://api.marketstack.com/v2", access_key="x")  # type: ignore[arg-type]
    async with httpx.AsyncClient() as http:
        client = MarketstackClient(http=http, settings=cfg)
        gw = MarketstackGateway(client=client)

        route = respx.get("https://api.marketstack.com/v2/eod").mock(
            return_value=httpx.Response(429, json={"error": {"code": "rate_limit"}})
        )

        q = HistoricalQueryDTO(
            tickers=["AAPL"],
            from_=datetime(2024, 1, 1, tzinfo=UTC),
            to=datetime(2024, 1, 2, tzinfo=UTC),
            interval=BarInterval.I1D,
            page=1,
            page_size=50,
        )

        with pytest.raises(MarketDataRateLimited):
            await gw.get_historical_bars(q)
        assert route.called


@pytest.mark.asyncio
@respx.mock
async def test_gateway_503_unavailable() -> None:
    cfg = MarketstackSettings(base_url="https://api.marketstack.com/v2", access_key="x")  # type: ignore[arg-type]
    async with httpx.AsyncClient() as http:
        client = MarketstackClient(http=http, settings=cfg)
        gw = MarketstackGateway(client=client)

        # Simulate network error on intraday call
        respx.get("https://api.marketstack.com/v2/intraday").mock(
            side_effect=httpx.NetworkError("boom")
        )

        q = HistoricalQueryDTO(
            tickers=["AAPL"],
            from_=datetime(2024, 1, 1, tzinfo=UTC),
            to=datetime(2024, 1, 2, tzinfo=UTC),
            interval=BarInterval.I5M,
            page=1,
            page_size=50,
        )

        with pytest.raises(MarketDataUnavailable):
            await gw.get_historical_bars(q)
