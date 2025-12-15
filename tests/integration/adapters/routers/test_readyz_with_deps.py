from __future__ import annotations

import asyncio
from typing import Any

import pytest
from fastapi.dependencies.utils import get_dependant
from fastapi.routing import APIRoute
from httpx import ASGITransport, AsyncClient

from arche_api.adapters.routers.health_router import HealthProbe
from arche_api.main import create_app


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


def _pick_readiness_route(app) -> APIRoute:
    """Return the readiness route (either /health/readiness or /health/ready)."""
    for r in app.routes:
        if isinstance(r, APIRoute) and r.path in ("/health/readiness", "/health/ready"):
            return r
    raise AssertionError("Readiness route not found on app")


def _collect_dependency_calls(route: APIRoute) -> list[Any]:
    """Collect dependency callable objects captured by FastAPI for a given route."""
    dependant = get_dependant(path=route.path_format, call=route.endpoint)
    calls: list[Any] = []

    def _walk(d) -> None:
        if getattr(d, "call", None) is not None:
            calls.append(d.call)
        for sub in getattr(d, "dependencies", []) or []:
            _walk(sub)

    _walk(dependant)
    return calls


def _find_readiness_dependency_callable(app) -> Any:
    """Return the exact dependency callable object the readiness route uses."""
    route = _pick_readiness_route(app)
    calls = _collect_dependency_calls(route)

    # Prefer well-known names first, then provider instances; else fallback to first dep.
    for c in calls:
        if getattr(c, "__name__", "") in {"resolve_probe", "get_health_probe"}:
            return c
    for c in calls:
        if c.__class__.__name__ in {"ProbeProvider"}:
            return c
    if not calls:
        raise AssertionError("No dependency callables found for readiness route")
    return calls[0]


@pytest.mark.anyio
async def test_readyz_200_when_all_ok(monkeypatch: pytest.MonkeyPatch) -> None:
    """Readiness returns 200 when both probes succeed (DI-only)."""
    monkeypatch.setenv("ENVIRONMENT", "staging")
    monkeypatch.setenv("ALLOWED_ORIGINS", "*")

    app = create_app()

    # Determine the exact DI key the route uses and override it
    di_key = _find_readiness_dependency_callable(app)
    app.dependency_overrides[di_key] = lambda: _GoodProbe()

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        r = await client.get("/health/ready")
        assert r.status_code == 200
        body = r.json()
        assert body["status"] == "ok"
        assert isinstance(body.get("checks"), list)


@pytest.mark.anyio
async def test_readyz_503_when_degraded(monkeypatch: pytest.MonkeyPatch) -> None:
    """Readiness returns 503 when a probe fails (DI-only)."""
    monkeypatch.setenv("ENVIRONMENT", "staging")
    monkeypatch.setenv("ALLOWED_ORIGINS", "*")

    app = create_app()

    di_key = _find_readiness_dependency_callable(app)
    app.dependency_overrides[di_key] = lambda: _BadProbe()

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        r = await client.get("/health/ready")
        assert r.status_code == 503
        body = r.json()
        assert body["status"] in {"degraded", "down"}
        assert any(c.get("status") == "down" for c in body["checks"])
