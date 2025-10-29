from __future__ import annotations

from collections.abc import Sequence
from datetime import UTC, datetime
from decimal import Decimal

import pytest
from fastapi import FastAPI
from httpx import AsyncClient
from pytest import MonkeyPatch

from stacklion_api.adapters.routers.quotes_router import router
from stacklion_api.application.use_cases.quotes.get_quotes import GetQuotes
from stacklion_api.dependencies import market_data as dep
from stacklion_api.domain.entities.quote import Quote
from stacklion_api.domain.interfaces.gateways.market_data_gateway import MarketDataGatewayProtocol


class FakeGateway(MarketDataGatewayProtocol):
    async def get_latest_quotes(self, tickers: Sequence[str]) -> list[Quote]:
        now = datetime.now(tz=UTC)
        return [
            Quote(ticker=t, price=Decimal("100.00"), currency="USD", as_of=now) for t in tickers
        ]


@pytest.mark.asyncio
async def test_get_quotes_200(monkeypatch: MonkeyPatch) -> None:
    app = FastAPI()
    app.include_router(router)

    async def _uc_override() -> GetQuotes:
        return GetQuotes(gateway=FakeGateway())

    app.dependency_overrides[dep.get_quotes_uc] = _uc_override

    async with AsyncClient(app=app, base_url="http://test") as client:
        r = await client.get("/v1/quotes", params={"tickers": "AAPL,MSFT"})
        assert r.status_code == 200
        body = r.json()
        assert [i["ticker"] for i in body["data"]["items"]] == ["AAPL", "MSFT"]


@pytest.mark.asyncio
async def test_get_quotes_304_with_etag(monkeypatch: MonkeyPatch) -> None:
    app = FastAPI()
    app.include_router(router)

    async def _uc_override() -> GetQuotes:
        return GetQuotes(gateway=FakeGateway())

    app.dependency_overrides[dep.get_quotes_uc] = _uc_override

    async with AsyncClient(app=app, base_url="http://test") as client:
        r1 = await client.get("/v1/quotes", params={"tickers": "AAPL"})
        assert r1.status_code == 200
        etag = r1.headers.get("ETag")
        r2 = await client.get(
            "/v1/quotes", params={"tickers": "AAPL"}, headers={"If-None-Match": etag}
        )
        assert r2.status_code == 304
