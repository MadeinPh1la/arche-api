from __future__ import annotations

import asyncio

import pytest
from httpx import ASGITransport, AsyncClient

from stacklion_api.adapters.routers.health_router import HealthProbe
from stacklion_api.main import create_app


class _GoodProbe(HealthProbe):
    async def db(self) -> tuple[bool, str | None]:
        await asyncio.sleep(0)
        return True, None

    async def redis(self) -> tuple[bool, str | None]:
        await asyncio.sleep(0)
        return True, None


class _BadProbe(HealthProbe):
    async def db(self) -> tuple[bool, str | None]:
        return False, "db down"

    async def redis(self) -> tuple[bool, str | None]:
        return False, "redis down"


@pytest.mark.anyio
async def test_readyz_200_when_all_ok(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("ENVIRONMENT", "staging")
    monkeypatch.setenv("ALLOWED_ORIGINS", "*")

    app = create_app()

    # Override DI to avoid touching real DB/Redis in tests
    from stacklion_api.adapters.routers.health_router import (
        get_health_probe,  # inline import for DI
    )

    async def _ok() -> _GoodProbe:
        return _GoodProbe()

    app.dependency_overrides[get_health_probe] = _ok

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        r = await client.get("/health/ready")
        assert r.status_code == 200
        body = r.json()
        assert body["status"] == "ok"
        assert isinstance(body.get("checks"), list)


@pytest.mark.anyio
async def test_readyz_503_when_degraded(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("ENVIRONMENT", "staging")
    monkeypatch.setenv("ALLOWED_ORIGINS", "*")

    app = create_app()

    from stacklion_api.adapters.routers.health_router import get_health_probe

    async def _bad() -> _BadProbe:
        return _BadProbe()

    app.dependency_overrides[get_health_probe] = _bad

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        r = await client.get("/health/ready")
        assert r.status_code == 503
        body = r.json()
        assert body["status"] in {"degraded", "down"}
        assert any(c.get("status") == "down" for c in body["checks"])
