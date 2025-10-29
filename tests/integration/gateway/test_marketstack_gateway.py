from __future__ import annotations

from decimal import Decimal
from typing import Any

import httpx
import pytest
import respx

from stacklion_api.infrastructure.external_apis.marketstack.client import MarketstackGateway
from stacklion_api.infrastructure.external_apis.marketstack.settings import MarketstackSettings

OK_BODY: dict[str, list[dict[str, Any]]] = {
    "data": [
        {
            "symbol": "AAPL",
            "last": 176.12,
            "date": "2025-10-28T12:00:00Z",
            "currency": "USD",
            "volume": 1000,
        },
        {"symbol": "MSFT", "last": "428.17", "date": "2025-10-28T12:00:00Z"},
    ]
}
EMPTY_BODY: dict[str, list[dict[str, Any]]] = {"data": []}
INVALID_BODY: dict[str, Any] = {"unexpected": True}


@pytest.mark.asyncio
async def test_success_mapping() -> None:
    cfg = MarketstackSettings(access_key="testkey")  # type: ignore[arg-type]
    async with httpx.AsyncClient() as client:
        gw = MarketstackGateway(client, cfg)
        with respx.mock:
            route = respx.get(f"{cfg.base_url}/intraday/latest").mock(
                return_value=httpx.Response(200, json=OK_BODY)
            )
            quotes = await gw.get_latest_quotes(["AAPL", "MSFT"])
            assert route.called
            assert [q.ticker for q in quotes] == ["AAPL", "MSFT"]
            assert quotes[0].price == Decimal("176.12")
            assert quotes[1].price == Decimal("428.17")


@pytest.mark.asyncio
async def test_symbol_not_found() -> None:
    cfg = MarketstackSettings(access_key="testkey")  # type: ignore[arg-type]
    async with httpx.AsyncClient() as client:
        gw = MarketstackGateway(client, cfg)
        with respx.mock:
            respx.get(f"{cfg.base_url}/intraday/latest").mock(
                return_value=httpx.Response(200, json=EMPTY_BODY)
            )
            from stacklion_api.domain.exceptions.market_data import SymbolNotFound

            with pytest.raises(SymbolNotFound):
                await gw.get_latest_quotes(["ZZZZ"])


@pytest.mark.asyncio
async def test_validation_error_on_shape_drift() -> None:
    cfg = MarketstackSettings(access_key="testkey")  # type: ignore[arg-type]
    async with httpx.AsyncClient() as client:
        gw = MarketstackGateway(client, cfg)
        with respx.mock:
            respx.get(f"{cfg.base_url}/intraday/latest").mock(
                return_value=httpx.Response(200, json=INVALID_BODY)
            )
            from stacklion_api.domain.exceptions.market_data import MarketDataValidationError

            with pytest.raises(MarketDataValidationError):
                await gw.get_latest_quotes(["AAPL"])
