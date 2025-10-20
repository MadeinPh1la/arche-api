from __future__ import annotations

import pytest
from httpx import AsyncClient, Response


@pytest.mark.anyio
async def test_rate_limit_emits_429_and_headers(
    http_client: AsyncClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    # Make the test deterministic: 1 request allowed per 60s -> 2nd should 429
    monkeypatch.setenv("RATE_LIMIT_ENABLED", "true")
    monkeypatch.setenv("RATE_LIMIT_BACKEND", "memory")
    monkeypatch.setenv("RATE_LIMIT_BURST", "1")
    monkeypatch.setenv("RATE_LIMIT_WINDOW_SECONDS", "60")

    path = "/openapi.json"  # pick any cheap, always-on route in your app

    # Two quick requests inside the same window
    responses: list[Response] = [
        await http_client.get(path),
        await http_client.get(path),
    ]

    # First should be 200-ish, second should be 429
    assert responses[0].status_code < 429
    assert responses[1].status_code == 429

    r429: Response = responses[1]
    assert "Retry-After" in r429.headers
    assert "X-RateLimit-Limit" in r429.headers
    assert "X-RateLimit-Remaining" in r429.headers

    # All responses should expose limit headers
    for r in responses:
        assert "X-RateLimit-Limit" in r.headers
        assert "X-RateLimit-Remaining" in r.headers
