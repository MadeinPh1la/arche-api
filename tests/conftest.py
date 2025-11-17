# tests/conftest.py
from __future__ import annotations

import asyncio
import os
import time
from collections.abc import AsyncGenerator, AsyncIterator, Callable, Generator
from contextlib import AbstractAsyncContextManager, asynccontextmanager
from datetime import UTC, datetime
from decimal import Decimal
from typing import Any

import httpx
import jwt
import pytest
from fastapi.testclient import TestClient
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncEngine, create_async_engine

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


@pytest.fixture(scope="session", autouse=True)
def _bootstrap_test_db_schema(event_loop: asyncio.AbstractEventLoop) -> None:
    """Ensure the minimal DB schema exists for tests (both local and CI).

    Creates:
        - public.md_intraday_bars_parent
        - staging.ingest_runs
        - staging.raw_payloads
    """
    database_url = os.getenv(
        "DATABASE_URL",
        "postgresql+asyncpg://stacklion:stacklion@127.0.0.1:5432/stacklion_test",
    )

    async def _init() -> None:
        engine: AsyncEngine = create_async_engine(database_url)
        async with engine.begin() as conn:
            # Ensure staging schema exists
            await conn.execute(text("CREATE SCHEMA IF NOT EXISTS staging"))

            # Minimal md_intraday_bars_parent table for intraday bar tests
            await conn.execute(
                text(
                    """
                    CREATE TABLE IF NOT EXISTS md_intraday_bars_parent (
                        symbol_id UUID NOT NULL,
                        ts TIMESTAMPTZ NOT NULL,
                        open NUMERIC(20, 8) NOT NULL,
                        high NUMERIC(20, 8) NOT NULL,
                        low NUMERIC(20, 8) NOT NULL,
                        close NUMERIC(20, 8) NOT NULL,
                        volume NUMERIC(38, 0) NOT NULL,
                        provider VARCHAR NOT NULL,
                        PRIMARY KEY (symbol_id, ts)
                    )
                    """
                )
            )

            # Minimal staging.ingest_runs table for ingest use case tests
            await conn.execute(
                text(
                    """
                    CREATE TABLE IF NOT EXISTS staging.ingest_runs (
                        run_id UUID PRIMARY KEY,
                        source VARCHAR NOT NULL,
                        endpoint VARCHAR NOT NULL,
                        key VARCHAR NOT NULL,
                        started_at TIMESTAMPTZ NOT NULL,
                        finished_at TIMESTAMPTZ,
                        result VARCHAR,
                        error_reason VARCHAR
                    )
                    """
                )
            )

            # Minimal staging.raw_payloads table for ingest staging payloads
            await conn.execute(
                text(
                    """
                    CREATE TABLE IF NOT EXISTS staging.raw_payloads (
                        payload_id UUID PRIMARY KEY,
                        source VARCHAR NOT NULL,
                        endpoint VARCHAR NOT NULL,
                        symbol_or_cik VARCHAR NOT NULL,
                        as_of TIMESTAMPTZ,
                        window_from TIMESTAMPTZ,
                        window_to TIMESTAMPTZ,
                        etag VARCHAR,
                        received_at TIMESTAMPTZ NOT NULL,
                        payload JSON NOT NULL
                    )
                    """
                )
            )

        await engine.dispose()

    # Run the async bootstrap on the session-scoped event loop
    event_loop.run_until_complete(_init())


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


@pytest.fixture
def valid_clerk_jwt() -> str:
    """Issue a short-lived HS256 test JWT for Clerk-protected routes."""
    payload = {"sub": "user_123", "iat": int(time.time()), "exp": int(time.time()) + 3600}
    return jwt.encode(payload, "testsecret", algorithm="HS256")
