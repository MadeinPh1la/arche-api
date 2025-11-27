# tests/unit/infrastructure/test_idempotency_middleware_unit.py
# Copyright (c) Stacklion.
# SPDX-License-Identifier: MIT
"""Unit tests for IdempotencyMiddleware control flow.

These tests avoid the database entirely by monkeypatching the repository and
hashing logic to force specific branches (e.g., IN_PROGRESS).
"""

from __future__ import annotations

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from datetime import datetime
from typing import Any

import pytest
from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse
from httpx import ASGITransport, AsyncClient

from stacklion_api.infrastructure.middleware import idempotency as idem_mod


class _FakeRecord:
    """Minimal in-memory IdempotencyRecord used for unit testing."""

    def __init__(self, *, key: str, request_hash: str) -> None:
        now = datetime.utcnow()
        self.key = key
        self.request_hash = request_hash
        self.method = "POST"
        self.path = "/unit-idempotent"
        self.status_code: int | None = None
        self.response_body: dict[str, Any] | None = None
        self.state = "STARTED"
        self.created_at = now
        self.updated_at = now
        self.expires_at = now  # value is irrelevant for this unit path


class _FakeRepo:
    """Fake repository that always returns an in-progress record."""

    def __init__(self, _session: object) -> None:
        self._record = _FakeRecord(key="test-key", request_hash="fixed-hash")

    async def get_active(self, key: str, *, now: datetime | None = None) -> _FakeRecord | None:
        return self._record

    async def create_started(
        self,
        *,
        key: str,
        request_hash: str,
        method: str,
        path: str,
        ttl_seconds: int,
        now: datetime | None = None,
    ) -> _FakeRecord:
        raise AssertionError("create_started() should not be called in this scenario")

    async def save_result(
        self,
        record: _FakeRecord,
        *,
        status_code: int,
        response_body: dict[str, Any] | None,
        now: datetime | None = None,
    ) -> None:
        raise AssertionError("save_result() should not be called in this scenario")


@asynccontextmanager
async def _dummy_session_provider() -> AsyncIterator[object]:
    """Session provider that yields a dummy object; DB is never touched."""
    yield object()


@pytest.mark.anyio
async def test_in_progress_record_returns_409(monkeypatch: pytest.MonkeyPatch) -> None:
    """Existing STARTED record with matching hash must yield IDEMPOTENCY_KEY_IN_PROGRESS."""
    # Force deterministic hashing so our fake record matches.
    monkeypatch.setattr(
        idem_mod.IdempotencyMiddleware,
        "_compute_request_hash",
        staticmethod(lambda _request, _body: "fixed-hash"),
    )
    # Swap the repository to our in-memory fake.
    monkeypatch.setattr(idem_mod, "IdempotencyRepository", _FakeRepo)

    app = FastAPI()
    app.add_middleware(
        idem_mod.IdempotencyMiddleware,
        ttl_seconds=3600,
        session_provider=_dummy_session_provider,
    )

    @app.post("/unit-idempotent")
    async def unit_idempotent(_request: Request) -> JSONResponse:
        return JSONResponse({"ok": True})

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://testserver") as client:
        r = await client.post(
            "/unit-idempotent",
            json={"token": "abc"},
            headers={"Idempotency-Key": "test-key"},
        )

    assert r.status_code == 409
    payload = r.json()
    assert payload["error"]["code"] == "IDEMPOTENCY_KEY_IN_PROGRESS"
