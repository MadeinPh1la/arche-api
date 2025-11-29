from __future__ import annotations

import jwt
import pytest
from _pytest.monkeypatch import MonkeyPatch
from httpx import AsyncClient


@pytest.mark.anyio
async def test_401_when_missing_token(http_client: AsyncClient, monkeypatch: MonkeyPatch) -> None:
    monkeypatch.setenv("AUTH_ENABLED", "true")
    monkeypatch.setenv("AUTH_HS256_SECRET", "testsecret")
    r = await http_client.get("/v1/protected/ping")
    assert r.status_code == 401


@pytest.mark.anyio
async def test_200_with_valid_hs256(http_client: AsyncClient, monkeypatch: MonkeyPatch) -> None:
    monkeypatch.setenv("AUTH_ENABLED", "true")
    monkeypatch.setenv("AUTH_HS256_SECRET", "testsecret")
    token = jwt.encode({"sub": "u1"}, "testsecret", algorithm="HS256")
    r = await http_client.get("/v1/protected/ping", headers={"Authorization": f"Bearer {token}"})
    assert r.status_code == 200
