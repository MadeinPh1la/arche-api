from __future__ import annotations

from typing import Any

import pytest
from fastapi import FastAPI, HTTPException
from fastapi.testclient import TestClient

from arche_api.infrastructure.middleware import request_metrics as rm
from arche_api.infrastructure.middleware.request_metrics import (
    RequestLatencyMiddleware,
)


class _FakeHistogram:
    def __init__(self) -> None:
        self.calls: list[tuple[str, str, str, float]] = []

    def labels(self, method: str, handler: str, status: str) -> _FakeHistogram:
        # store labels; observe() will append the value
        self._current_labels = (method, handler, status)
        return self

    def observe(self, value: float) -> None:
        method, handler, status = self._current_labels
        self.calls.append((method, handler, status, value))


def _make_app_with_middleware(fake_hist: _FakeHistogram) -> FastAPI:
    app = FastAPI()

    @app.get("/ok")
    async def ok() -> dict[str, str]:
        return {"status": "ok"}

    @app.get("/bad")
    async def bad() -> None:
        raise HTTPException(status_code=400, detail="bad request")

    # Patch histogram creation before middleware is instantiated
    def fake_get_or_create_hist(*_: Any, **__: Any) -> _FakeHistogram:
        return fake_hist

    rm._SERVER_HIST = None  # ensure we don't reuse a previous histogram
    rm._get_or_create_hist = fake_get_or_create_hist  # type: ignore[assignment]

    app.add_middleware(RequestLatencyMiddleware)
    return app


def test_request_latency_middleware_records_success(monkeypatch: pytest.MonkeyPatch) -> None:
    fake_hist = _FakeHistogram()
    app = _make_app_with_middleware(fake_hist)
    client = TestClient(app)

    resp = client.get("/ok")
    assert resp.status_code == 200

    assert len(fake_hist.calls) == 1
    method, handler, status, duration = fake_hist.calls[0]
    assert method == "GET"
    assert handler.endswith("/ok")
    assert status == "200"
    assert duration >= 0.0


def test_request_latency_middleware_records_client_error() -> None:
    fake_hist = _FakeHistogram()
    app = _make_app_with_middleware(fake_hist)
    client = TestClient(app)

    resp = client.get("/bad")
    assert resp.status_code == 400

    # two calls total now: one from /bad in this test
    assert len(fake_hist.calls) == 1
    method, handler, status, duration = fake_hist.calls[0]
    assert method == "GET"
    assert handler.endswith("/bad")
    assert status == "400"
    assert duration >= 0.0
