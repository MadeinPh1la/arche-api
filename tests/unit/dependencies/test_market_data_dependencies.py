# Copyright (c) Stacklion.
# SPDX-License-Identifier: MIT
from __future__ import annotations

import asyncio
import os
from datetime import UTC, datetime
from decimal import Decimal

import pytest

from stacklion_api.application.schemas.dto.quotes import HistoricalBarDTO
from stacklion_api.dependencies.market_data import (
    DeterministicMarketDataGateway,
    InMemoryAsyncCache,
    _is_deterministic_mode,  # intentionally testing private helper
)
from stacklion_api.domain.entities.historical_bar import BarInterval
from stacklion_api.domain.exceptions.market_data import MarketDataValidationError
from stacklion_api.infrastructure.external_apis.marketstack.settings import MarketstackSettings


def test_is_deterministic_mode_env_test() -> None:
    os.environ["ENVIRONMENT"] = "test"
    s = MarketstackSettings(base_url="u", access_key="", timeout_s=1.0, max_retries=0)
    assert _is_deterministic_mode(s) is True
    os.environ.pop("ENVIRONMENT", None)


def test_is_deterministic_mode_stacklion_flag() -> None:
    os.environ["STACKLION_TEST_MODE"] = "1"
    s = MarketstackSettings(base_url="u", access_key="x", timeout_s=1.0, max_retries=0)
    assert _is_deterministic_mode(s) is True
    os.environ.pop("STACKLION_TEST_MODE", None)


def test_is_deterministic_mode_empty_key() -> None:
    s = MarketstackSettings(base_url="u", access_key="", timeout_s=1.0, max_retries=0)
    assert _is_deterministic_mode(s) is True


@pytest.mark.asyncio
async def test_inmemory_async_cache_roundtrip_and_expire() -> None:
    cache = InMemoryAsyncCache()

    # Use a short positive TTL so first read is a hit, then it expires.
    await cache.set_json("k", {"v": 1}, ttl=1)
    got = await cache.get_json("k")
    assert got == {"v": 1}

    # After TTL elapses, lazy eviction should return None.
    await asyncio.sleep(1.1)
    assert await cache.get_json("k") is None

    # ttl=0 should be considered immediately expired (documented behavior).
    await cache.set_json("k0", {"v": 0}, ttl=0)
    assert await cache.get_json("k0") is None


@pytest.mark.asyncio
async def test_deterministic_gateway_returns_expected_bar() -> None:
    gw = DeterministicMarketDataGateway()
    items, total, etag = await gw.get_historical_bars(
        tickers=["AAPL"],
        date_from=datetime(2025, 1, 1, tzinfo=UTC),
        date_to=datetime(2025, 1, 2, tzinfo=UTC),
        interval=BarInterval.I1D,
        limit=50,
        offset=0,
    )
    assert total == 1 and etag.startswith('W/"')
    bar: HistoricalBarDTO = items[0]
    assert bar.ticker == "AAPL"
    assert bar.close == Decimal("1.5")


@pytest.mark.asyncio
async def test_deterministic_gateway_raises_on_bad_window() -> None:
    gw = DeterministicMarketDataGateway()
    with pytest.raises(MarketDataValidationError):
        await gw.get_historical_bars(
            tickers=["AAPL"],
            date_from=datetime(2025, 1, 3, tzinfo=UTC),
            date_to=datetime(2025, 1, 2, tzinfo=UTC),
            interval=BarInterval.I1D,
            limit=1,
            offset=0,
        )
