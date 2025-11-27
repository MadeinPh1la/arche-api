# tests/integration/middleware/test_idempotency_middleware.py
# Copyright (c) Stacklion.
# SPDX-License-Identifier: MIT
"""Integration tests for IdempotencyMiddleware.

These tests exercise the end-to-end HTTP path:

    FastAPI → IdempotencyMiddleware → dummy handler → DB-backed repo.
"""

from __future__ import annotations

import os
from collections.abc import AsyncGenerator, AsyncIterator
from contextlib import asynccontextmanager
from datetime import datetime, timedelta
from uuid import uuid4

import httpx
import pytest
from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse, PlainTextResponse
from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)

from stacklion_api.infrastructure.database.models.idempotency import IdempotencyKey
from stacklion_api.infrastructure.middleware.idempotency import IdempotencyMiddleware


def _utcnow_naive() -> datetime:
    """Return naive UTC for idempotency tests."""
    return datetime.utcnow()


@pytest.fixture(scope="module")
async def app() -> AsyncGenerator[FastAPI, None]:
    """FastAPI app with idempotency middleware and dummy routes.

    We inject a custom session_provider that:
        * Creates an engine per request.
        * Ensures the idempotency table exists.
        * Yields a single AsyncSession.
        * Disposes the engine afterwards.

    This avoids asyncpg's 'different loop' and 'operation in progress' issues in tests.
    """

    @asynccontextmanager
    async def session_provider() -> AsyncIterator[AsyncSession]:
        database_url = os.getenv(
            "DATABASE_URL",
            "postgresql+asyncpg://stacklion:stacklion@127.0.0.1:5432/stacklion_test",
        )
        engine: AsyncEngine = create_async_engine(database_url, future=True)

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

    @app.get("/idempotent")
    async def idempotent_get() -> JSONResponse:
        """GET variant to verify that non-write methods bypass idempotency."""
        now = _utcnow_naive().isoformat()
        return JSONResponse({"method": "GET", "as_of": now})

    @app.post("/plaintext")
    async def plaintext_endpoint(request: Request) -> PlainTextResponse:
        """Non-JSON endpoint to exercise the non-JSON response branch."""
        body = await request.body()
        token = body.decode("utf-8") if body else "ok"
        return PlainTextResponse(token, status_code=201)

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


@pytest.mark.anyio
async def test_requests_without_header_bypass_idempotency(client: httpx.AsyncClient) -> None:
    """Requests without Idempotency-Key must behave as normal, non-idempotent writes."""
    payload = {"token": "abc"}

    r1 = await client.post("/idempotent", json=payload)
    r2 = await client.post("/idempotent", json=payload)

    assert r1.status_code == 200
    assert r2.status_code == 200
    # No 409s; we don't assert response equality here because the handler embeds a timestamp.


@pytest.mark.anyio
async def test_get_method_not_subject_to_idempotency_even_with_header(
    client: httpx.AsyncClient,
) -> None:
    """Non-write methods should bypass idempotency logic even if the header is present."""
    key = "idem-" + str(uuid4())

    r1 = await client.get("/idempotent", headers={"Idempotency-Key": key})
    r2 = await client.get("/idempotent", headers={"Idempotency-Key": key})

    assert r1.status_code == 200
    assert r2.status_code == 200
    # No 409 conflicts; middleware only applies to configured write methods.


@pytest.mark.anyio
async def test_expired_record_allows_new_execution(client: httpx.AsyncClient) -> None:
    """Expired idempotency records must not block a new execution with the same key."""
    key = "idem-expired-" + str(uuid4())

    # Pre-insert an expired *started* record for this key.
    database_url = os.getenv(
        "DATABASE_URL",
        "postgresql+asyncpg://stacklion:stacklion@127.0.0.1:5432/stacklion_test",
    )
    engine: AsyncEngine = create_async_engine(database_url, future=True)
    async with engine.begin() as conn:
        await conn.run_sync(IdempotencyKey.__table__.create, checkfirst=True)

    session_factory = async_sessionmaker(engine, expire_on_commit=False, class_=AsyncSession)

    async with session_factory() as session:
        started = IdempotencyKey.new_started(
            key=key,
            request_hash="irrelevant-hash",
            method="POST",
            path="/idempotent",
            ttl_seconds=60,
            now=_utcnow_naive() - timedelta(hours=2),
        )
        session.add(started)
        await session.commit()

    await engine.dispose()

    # Now send a POST with the same key. Because the record is expired, it should
    # not cause a 409 and the handler should run normally.
    r = await client.post(
        "/idempotent",
        json={"token": "abc"},
        headers={"Idempotency-Key": key},
    )
    assert r.status_code == 200
    body = r.json()
    assert body["token"] == "abc"  # noqa: S105


@pytest.mark.anyio
async def test_non_json_response_is_handled_and_replayed_status_only(
    client: httpx.AsyncClient,
) -> None:
    """Non-JSON responses should be stored with no body and replayed by status code only."""
    key = "idem-plaintext-" + str(uuid4())

    # First call stores a 201 + plaintext body.
    r1 = await client.post(
        "/plaintext",
        content=b"hello",
        headers={"Idempotency-Key": key},
    )
    assert r1.status_code == 201
    assert r1.text == "hello"

    # Second call should hit the *completed* record. Middleware will replay only
    # the status code (no body), because it could not JSON-decode the payload.
    r2 = await client.post(
        "/plaintext",
        content=b"hello",
        headers={"Idempotency-Key": key},
    )
    assert r2.status_code == 201
    assert r2.text == ""
