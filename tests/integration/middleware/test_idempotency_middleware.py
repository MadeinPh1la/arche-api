# tests/integration/middleware/test_idempotency_middleware.py
# Copyright (c) Stacklion.
# SPDX-License-Identifier: MIT
"""
Integration tests for IdempotencyMiddleware.

These tests exercise the end-to-end HTTP path:

    FastAPI → IdempotencyMiddleware → dummy handler → DB-backed repo.
"""

from __future__ import annotations

from collections.abc import AsyncGenerator, AsyncIterator
from contextlib import asynccontextmanager
from datetime import datetime
from uuid import uuid4

import httpx
import pytest
from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse
from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)

from stacklion_api.config.settings import get_settings
from stacklion_api.infrastructure.database.models.idempotency import IdempotencyKey
from stacklion_api.infrastructure.middleware.idempotency import IdempotencyMiddleware


def _utcnow_naive() -> datetime:
    """Return naive UTC for idempotency tests."""
    return datetime.utcnow()


@pytest.fixture(scope="module")
async def app() -> AsyncGenerator[FastAPI, None]:
    """FastAPI app with idempotency middleware and a dummy write route.

    We inject a custom session_provider that:
        * Creates an engine per request.
        * Ensures the idempotency table exists.
        * Yields a single AsyncSession.
        * Disposes the engine afterwards.

    This avoids asyncpg's 'different loop' and 'operation in progress' issues in tests.
    """

    @asynccontextmanager
    async def session_provider() -> AsyncIterator[AsyncSession]:
        settings = get_settings()
        engine: AsyncEngine = create_async_engine(settings.database_url, future=True)

        # Ensure table exists for this request.
        async with engine.begin() as conn:
            await conn.run_sync(IdempotencyKey.__table__.create, checkfirst=True)

        session_factory = async_sessionmaker(engine, expire_on_commit=False, class_=AsyncSession)

        async with session_factory() as session:
            try:
                yield session
            finally:
                await session.rollback()

        await engine.dispose()

    app = FastAPI()
    app.add_middleware(
        IdempotencyMiddleware,
        ttl_seconds=3600,
        session_provider=session_provider,
    )

    @app.post("/idempotent")
    async def idempotent_endpoint(request: Request) -> JSONResponse:
        """Dummy handler that returns a deterministic payload."""
        body = await request.json()
        token = body.get("token") or "default"
        now = _utcnow_naive().isoformat()
        return JSONResponse({"token": token, "as_of": now})

    yield app


@pytest.fixture
async def client(app: FastAPI) -> AsyncGenerator[httpx.AsyncClient, None]:
    """HTTP client bound to the FastAPI ASGI app via ASGITransport."""
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://testserver") as c:
        yield c


@pytest.mark.anyio
async def test_same_key_same_payload_returns_same_response(client: httpx.AsyncClient) -> None:
    """Same Idempotency-Key + same payload should replay the same response body."""
    key = "idem-" + str(uuid4())
    payload = {"token": "abc"}

    r1 = await client.post(
        "/idempotent",
        json=payload,
        headers={"Idempotency-Key": key},
    )
    assert r1.status_code == 200
    body1 = r1.json()

    r2 = await client.post(
        "/idempotent",
        json=payload,
        headers={"Idempotency-Key": key},
    )
    assert r2.status_code == 200
    body2 = r2.json()

    assert body1 == body2


@pytest.mark.anyio
async def test_conflicting_payload_with_same_key_returns_409(client: httpx.AsyncClient) -> None:
    """Same Idempotency-Key + different payload must return a 409 conflict."""
    key = "idem-" + str(uuid4())

    r1 = await client.post(
        "/idempotent",
        json={"token": "abc"},
        headers={"Idempotency-Key": key},
    )
    assert r1.status_code == 200

    r2 = await client.post(
        "/idempotent",
        json={"token": "xyz"},
        headers={"Idempotency-Key": key},
    )

    assert r2.status_code == 409
    body = r2.json()
    assert body["error"]["code"] == "IDEMPOTENCY_KEY_CONFLICT"
