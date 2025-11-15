# tests/unit/dependencies/test_market_data_real_gateway_and_cache.py
from __future__ import annotations

import asyncio
from dataclasses import dataclass
from datetime import UTC, datetime
from decimal import Decimal
from typing import Any

import pytest
from pydantic import BaseModel, SecretStr

from stacklion_api.application.schemas.dto.quotes import HistoricalBarDTO, HistoricalQueryDTO
from stacklion_api.application.use_cases.quotes.get_historical_quotes import (
    GetHistoricalQuotesUseCase,
)
from stacklion_api.dependencies.market_data import (
    InMemoryAsyncCache,
    _build_real_gateway,
    _is_deterministic_mode,
    _load_marketstack_settings,
)
from stacklion_api.domain.entities.historical_bar import BarInterval
from stacklion_api.domain.exceptions.market_data import MarketDataValidationError
from stacklion_api.infrastructure.external_apis.marketstack.settings import (
    MarketstackSettings,
)


@dataclass
class _FakeSettings:
    marketstack_base_url: str = "https://example.local/api"
    marketstack_api_key: str = "test-key"
    marketstack_timeout_s: float = 1.23
    marketstack_max_retries: int = 7


def test_load_marketstack_settings_prefers_app_settings(monkeypatch: pytest.MonkeyPatch) -> None:
    """_load_marketstack_settings should prefer app Settings over raw env."""
    # Arrange fake Settings
    fake = _FakeSettings()

    class _Wrapper(BaseModel):
        marketstack_base_url: str = fake.marketstack_base_url
        marketstack_api_key: str = fake.marketstack_api_key
        marketstack_timeout_s: float = fake.marketstack_timeout_s
        marketstack_max_retries: int = fake.marketstack_max_retries

    def _fake_get_settings() -> Any:
        return _Wrapper()

    monkeypatch.setenv("MARKETSTACK_ACCESS_KEY", "ignored-env-key")
    monkeypatch.setenv("MARKETSTACK_BASE_URL", "https://wrong.example.com")

    # Patch get_settings used by dependencies.market_data
    import stacklion_api.dependencies.market_data as md

    monkeypatch.setattr(md, "get_settings", _fake_get_settings, raising=True)

    # Act
    ms = _load_marketstack_settings()

    # Assert it used the fake settings, not the env
    assert ms.base_url == fake.marketstack_base_url
    assert ms.access_key.get_secret_value() == fake.marketstack_api_key
    assert ms.timeout_s == fake.marketstack_timeout_s
    assert ms.max_retries == fake.marketstack_max_retries


def test_build_real_gateway_requires_key() -> None:
    """_build_real_gateway without a key should raise MarketDataValidationError."""
    ms = MarketstackSettings(
        base_url="https://example.local/api",
        access_key=SecretStr(""),
        timeout_s=2.0,
        max_retries=0,
    )
    with pytest.raises(MarketDataValidationError):
        _build_real_gateway(ms)


def test_inmemory_cache_raw_helpers_respect_ttl() -> None:
    """set_raw/get_raw should round-trip JSON and respect ttl semantics."""
    cache = InMemoryAsyncCache()

    async def _run() -> None:
        await cache.set_raw("k", b'{"v": 1}', ttl=1)
        got = await cache.get_raw("k")
        assert got == b'{"v": 1}'
        await asyncio.sleep(1.1)
        assert await cache.get_raw("k") is None

    asyncio.run(_run())


def test_is_deterministic_mode_non_test_env_with_key(monkeypatch: pytest.MonkeyPatch) -> None:
    """Ensure non-empty key and no test flags uses real gateway mode."""
    ms = MarketstackSettings(
        base_url="https://example.local/api",
        access_key=SecretStr("non-empty"),
        timeout_s=2.0,
        max_retries=0,
    )
    monkeypatch.delenv("ENVIRONMENT", raising=False)
    monkeypatch.delenv("STACKLION_TEST_MODE", raising=False)

    assert _is_deterministic_mode(ms) is False


class _PositionalGateway:
    """Gateway that only supports positional get_historical_bars signature."""

    def __init__(self) -> None:
        self.calls: list[tuple] = []

    async def get_historical_bars(self, *args: Any) -> tuple[list[HistoricalBarDTO], int]:
        # tickers, date_from, date_to, interval, limit, offset
        self.calls.append(args)
        ticker_list, date_from, date_to, interval, limit, offset = args
        assert ticker_list == ["AAPL"]
        assert isinstance(date_from, datetime)
        assert isinstance(date_to, datetime)
        assert interval is BarInterval.I1D
        assert limit == 50
        assert offset == 0
        dto = HistoricalBarDTO(
            ticker="AAPL",
            timestamp=datetime(2025, 1, 2, tzinfo=UTC),
            open=Decimal("1"),
            high=Decimal("2"),
            low=Decimal("0.5"),
            close=Decimal("1.5"),
            volume=Decimal("10"),
            interval=interval,
        )
        return [dto], 1


@pytest.mark.asyncio
async def test_uc_hits_positional_gateway_signature() -> None:
    """Exercise the UC branch that falls back to positional get_historical_bars signature."""
    cache = InMemoryAsyncCache()
    gw = _PositionalGateway()
    uc = GetHistoricalQuotesUseCase(cache=cache, gateway=gw)
    q = HistoricalQueryDTO(
        tickers=["AAPL"],
        from_=datetime(2025, 1, 1, tzinfo=UTC),
        to=datetime(2025, 1, 2, tzinfo=UTC),
        interval=BarInterval.I1D,
        page=1,
        page_size=50,
    )

    items, total, etag = await uc.execute(q)
    assert total == 1
    assert items[0].ticker == "AAPL"
    assert etag.startswith('W/"')
    # Ensure we actually hit the positional signature branch
    assert len(gw.calls) == 1
