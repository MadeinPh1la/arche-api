# tests/integration/routers/test_rate_limit_headers_a2.py
import pytest
from httpx import AsyncClient

from stacklion_api.main import create_app


@pytest.mark.anyio
async def test_rate_limit_emits_429_and_headers(monkeypatch: pytest.MonkeyPatch) -> None:
    # Configure limiter BEFORE creating the app
    monkeypatch.setenv("ENVIRONMENT", "staging")
    monkeypatch.setenv("ALLOWED_ORIGINS", "*")
    monkeypatch.setenv("RATE_LIMIT_ENABLED", "true")
    monkeypatch.setenv("RATE_LIMIT_BACKEND", "memory")
    monkeypatch.setenv("RATE_LIMIT_BURST", "3")
    monkeypatch.setenv("RATE_LIMIT_WINDOW_SECONDS", "1")

    app = create_app()  # app reads env once here
    async with AsyncClient(app=app, base_url="http://test") as client:
        # /healthz has a built-in, deterministic limiter (separate from middleware)
        for _ in range(3):
            ok = await client.get("/healthz")
            assert ok.status_code == 200

        limited = await client.get("/healthz")
        assert limited.status_code == 429

        # Headers should be present
        for h in ("X-RateLimit-Limit", "X-RateLimit-Remaining", "X-RateLimit-Reset", "Retry-After"):
            assert h in limited.headers, f"missing header: {h}"
