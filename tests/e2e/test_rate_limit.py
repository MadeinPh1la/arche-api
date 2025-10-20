from __future__ import annotations

from collections.abc import Callable
from contextlib import AbstractAsyncContextManager

import httpx
import pytest


@pytest.mark.anyio
async def test_rate_limit_headers_and_429(
    http_client_factory: Callable[[], AbstractAsyncContextManager[httpx.AsyncClient]],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("RATE_LIMIT_ENABLED", "true")
    monkeypatch.setenv("RATE_LIMIT_BACKEND", "memory")
    monkeypatch.setenv("RATE_LIMIT_BURST", "5")
    monkeypatch.setenv("RATE_LIMIT_WINDOW_SECONDS", "1")

    async with http_client_factory() as http_client:
        hits: list[int] = []
        for _ in range(8):
            r = await http_client.get("/healthz")
            hits.append(r.status_code)

    assert 429 in hits
