from __future__ import annotations

import asyncio
from collections.abc import AsyncGenerator, AsyncIterator, Callable, Generator
from contextlib import AbstractAsyncContextManager, asynccontextmanager
from typing import Any

import httpx
import pytest

from stacklion_api.config.settings import get_settings
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
