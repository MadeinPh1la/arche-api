from __future__ import annotations

import asyncio
from collections.abc import AsyncGenerator, AsyncIterator, Callable, Generator
from contextlib import AbstractAsyncContextManager, asynccontextmanager
from datetime import UTC, datetime
from decimal import Decimal
from typing import Any

import httpx
import pytest
from fastapi.testclient import TestClient

from stacklion_api.application.schemas.dto.quotes import HistoricalBarDTO
from stacklion_api.config.settings import get_settings
from stacklion_api.dependencies.market_data import get_historical_quotes_use_case
from stacklion_api.domain.entities.historical_bar import BarInterval
from stacklion_api.main import create_app


@pytest.fixture(scope="session")
def event_loop() -> Generator[asyncio.AbstractEventLoop, None, None]:
    """Provide a dedicated event loop for the test session."""
    loop = asyncio.new_event_loop()
    try:
        yield loop
    finally:
        loop.close()


@asynccontextmanager
async def _make_client() -> AsyncIterator[httpx.AsyncClient]:
    """Create an AsyncClient bound to a fresh app (reads env at call time)."""
    # Ensure settings reflect env set in the test before app creation
    cache_clear = getattr(get_settings, "cache_clear", None)
    if callable(cache_clear):
        cache_clear()

    app = create_app()
    transport = httpx.ASGITransport(app=app)
    client = httpx.AsyncClient(transport=transport, base_url="http://testserver")
    try:
        yield client
    finally:
        await client.aclose()


@pytest.fixture
def http_client_factory() -> Callable[[], AbstractAsyncContextManager[httpx.AsyncClient]]:
    """
    Factory fixture for tests that set env inside the test:

        async with http_client_factory() as c:
            r = await c.get("/healthz")
    """
    return _make_client


class _LazyAsyncClient:
    """Lazily creates the real client on first use so env set in-test takes effect."""

    def __init__(self) -> None:
        self._client: httpx.AsyncClient | None = None

    async def _ensure(self) -> None:
        if self._client is None:
            cache_clear = getattr(get_settings, "cache_clear", None)
            if callable(cache_clear):
                cache_clear()
            app = create_app()
            transport = httpx.ASGITransport(app=app)
            self._client = httpx.AsyncClient(transport=transport, base_url="http://testserver")

    async def request(self, method: str, url: str, **kwargs: Any) -> httpx.Response:
        await self._ensure()
        assert self._client is not None
        return await self._client.request(method, url, **kwargs)

    async def get(self, url: str, **kwargs: Any) -> httpx.Response:
        return await self.request("GET", url, **kwargs)

    async def post(self, url: str, **kwargs: Any) -> httpx.Response:
        return await self.request("POST", url, **kwargs)

    async def put(self, url: str, **kwargs: Any) -> httpx.Response:
        return await self.request("PUT", url, **kwargs)

    async def patch(self, url: str, **kwargs: Any) -> httpx.Response:
        return await self.request("PATCH", url, **kwargs)

    async def delete(self, url: str, **kwargs: Any) -> httpx.Response:
        return await self.request("DELETE", url, **kwargs)

    async def aclose(self) -> None:
        if self._client is not None:
            await self._client.aclose()
            self._client = None


@pytest.fixture
async def http_client() -> AsyncGenerator[_LazyAsyncClient, None]:
    """Fixture for tests that expect `http_client` directly."""
    lazy = _LazyAsyncClient()
    try:
        yield lazy
    finally:
        await lazy.aclose()


@pytest.fixture(scope="session")
def anyio_backend() -> str:
    """Force pytest-anyio to use asyncio (not trio)."""
    return "asyncio"


class _TestFakeUC:
    """Deterministic UC used only when tests opt-in via @pytest.mark.use_fake_uc."""

    def __init__(self, etag: str = 'W/"abc123"') -> None:
        self._etag = etag

    async def execute(self, q, *, if_none_match: str | None = None):
        # Stable data; mirrors router integration test’s expectations.
        item = HistoricalBarDTO(
            ticker=(q.tickers[0] if q.tickers else "AAPL"),
            timestamp=datetime(2025, 1, 2, tzinfo=UTC),
            open=Decimal("1"),
            high=Decimal("2"),
            low=Decimal("0.5"),
            close=Decimal("1.5"),
            volume=Decimal("10"),
            interval=(
                BarInterval.I1D if str(q.interval) in {"1d", "BarInterval.I1D"} else BarInterval.I1M
            ),
        )
        return [item], 1, self._etag


def pytest_configure(config: pytest.Config) -> None:
    config.addinivalue_line(
        "markers", "use_fake_uc: override the historical quotes UC with a fake."
    )


@pytest.fixture
def app(request: pytest.FixtureRequest):
    """Create app; if test is marked `use_fake_uc`, override UC to `_TestFakeUC`."""
    app = create_app()
    marker = request.node.get_closest_marker("use_fake_uc")
    if marker is not None:
        app.dependency_overrides[get_historical_quotes_use_case] = lambda: _TestFakeUC()
    yield app


@pytest.fixture
def client(app):
    """Default client for tests that rely on TestClient."""
    return TestClient(app)


@pytest.fixture
async def app_client(app) -> AsyncGenerator[httpx.AsyncClient, None]:
    """Async HTTP client bound to the per-test FastAPI app (respects @use_fake_uc)."""
    transport = httpx.ASGITransport(app=app)
    client = httpx.AsyncClient(transport=transport, base_url="http://testserver")
    try:
        yield client
    finally:
        await client.aclose()
