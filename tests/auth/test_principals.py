import os

import pytest
from httpx import AsyncClient

pytestmark = pytest.mark.skipif(
    os.getenv("AUTH_PRINCIPALS_PARITY_ENABLED", "0") != "1",
    reason="PR-06 Auth Principals Parity not enabled on this branch",
)


@pytest.mark.anyio
async def test_api_key_principal(app_client: AsyncClient):
    r = await app_client.get("/companies", headers={"x-api-key": "test_valid_key"})
    assert r.status_code == 200
    assert "trace_id" in r.json()


@pytest.mark.anyio
async def test_jwt_principal(app_client: AsyncClient, valid_clerk_jwt: str):
    r = await app_client.get("/companies", headers={"authorization": f"Bearer {valid_clerk_jwt}"})
    assert r.status_code == 200
