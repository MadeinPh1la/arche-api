# tests/unit/adapters/gateways/test_marketstack_gateway_unit.py
# Copyright (c) Arche.
# SPDX-License-Identifier: MIT

from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path

import httpx
import pytest
import respx

from arche_api.adapters.gateways.marketstack_gateway import MarketstackGateway
from arche_api.application.schemas.dto.quotes import HistoricalQueryDTO
from arche_api.domain.entities.historical_bar import BarInterval
from arche_api.domain.exceptions.market_data import (
    MarketDataRateLimited,
    MarketDataValidationError,
)
from arche_api.infrastructure.external_apis.marketstack.settings import MarketstackSettings

_BASE_URL = "https://api.marketstack.com/v2"
_EOD_URL_REGEX = r"https://api\.marketstack\.com/v2/eod.*"
_INTRADAY_URL_REGEX = r"https://api\.marketstack\.com/v2/intraday.*"


def _load_payload() -> dict:
    """Load a sample Marketstack EOD payload from disk."""
    return json.loads(Path("tests/data/marketstack_eod.json").read_text())


@pytest.fixture
def settings() -> MarketstackSettings:
    """Fixture providing Marketstack settings wired for the V2 API."""
    return MarketstackSettings(
        base_url=_BASE_URL,
        access_key="test",
        timeout_s=2.0,
        max_retries=0,
    )


@pytest.mark.asyncio
@respx.mock
async def test_eod_happy_path(settings: MarketstackSettings) -> None:
    """Happy path: EOD request returns mapped historical bars and total count."""
    payload = _load_payload()
    route = respx.get(url__regex=_EOD_URL_REGEX).mock(
        return_value=httpx.Response(200, json=payload),
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
    assert items
    assert items[0].ticker == "AAPL"


@pytest.mark.asyncio
@respx.mock
async def test_intraday_rate_limited_raises(settings: MarketstackSettings) -> None:
    """429 from intraday endpoint should surface as MarketDataRateLimited."""
    respx.get(url__regex=_INTRADAY_URL_REGEX).mock(
        return_value=httpx.Response(429, json={"error": {"code": "rate_limit"}}),
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
async def test_bad_shape_raises_validation(settings: MarketstackSettings) -> None:
    """Non-conforming payload (missing `data` list) should raise validation error."""
    respx.get(url__regex=_EOD_URL_REGEX).mock(
        return_value=httpx.Response(200, json={"nope": []}),
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
