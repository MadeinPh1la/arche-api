from __future__ import annotations

from typing import Any

import pytest
from fastapi import FastAPI
from fastapi.responses import PlainTextResponse
from fastapi.testclient import TestClient

from arche_api.infrastructure.middleware.request_metrics import RequestLatencyMiddleware


def _make_app_with_middleware() -> FastAPI:
    app = FastAPI()

    @app.get("/ping")
    async def ping() -> PlainTextResponse:
        return PlainTextResponse("ok")

    app.add_middleware(RequestLatencyMiddleware)
    return app


class _BadLabels:
    def observe(self, _value: float) -> None:
        raise RuntimeError("observe failed")


class _BadHistogram:
    def labels(self, *_: Any, **__: Any) -> _BadLabels:
        return _BadLabels()


class _BadOtelHistogram:
    def record(self, *_: Any, **__: Any) -> None:
        raise RuntimeError("otel record failed")


def test_request_latency_prometheus_error_does_not_break_request(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """If the Prometheus histogram labels/observe call fails, the request
    still succeeds and the error path is logged (branch coverage).
    """
    # Force RequestLatencyMiddleware to use a histogram that throws.
    monkeypatch.setattr(
        "arche_api.infrastructure.middleware.request_metrics.get_http_server_request_duration_seconds",
        lambda: _BadHistogram(),
    )

    app = _make_app_with_middleware()
    client = TestClient(app)

    resp = client.get("/ping")
    assert resp.status_code == 200
    assert resp.text == "ok"


def test_request_latency_otel_error_does_not_break_request(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """If OTEL histogram.record fails, the request still succeeds and the
    otel.histogram_record_failed branch is covered.
    """
    # Patch the module-level _otel_hist() helper to return a broken histogram.
    monkeypatch.setattr(
        "arche_api.infrastructure.middleware.request_metrics._otel_hist",
        lambda: _BadOtelHistogram(),
    )

    app = _make_app_with_middleware()
    client = TestClient(app)

    resp = client.get("/ping")
    assert resp.status_code == 200
    assert resp.text == "ok"
