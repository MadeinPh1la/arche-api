from __future__ import annotations

from typing import Any

from fastapi import FastAPI, HTTPException, Request
from fastapi.exceptions import RequestValidationError
from fastapi.testclient import TestClient
from pydantic import BaseModel

from stacklion_api.infrastructure.http import errors


class Payload(BaseModel):
    """Simple request body model used to exercise validation handlers."""

    value: int


def test_error_envelope_includes_optional_fields() -> None:
    """error_envelope should include all optional fields when provided."""
    payload = errors.error_envelope(
        code="SOME_CODE",
        http_status=418,
        message="I'm a teapot",
        details={"extra": "info"},
        trace_id="trace-123",
    )

    err = payload["error"]
    assert err["code"] == "SOME_CODE"
    assert err["http_status"] == 418
    assert err["message"] == "I'm a teapot"
    assert err["details"] == {"extra": "info"}
    assert err["trace_id"] == "trace-123"


def _make_app_with_handlers() -> FastAPI:
    """Build a FastAPI app wired with the custom error handlers under test."""
    app = FastAPI()

    # Attach handlers from our module
    app.add_exception_handler(RequestValidationError, errors.handle_validation_error)
    app.add_exception_handler(HTTPException, errors.handle_http_exception)
    app.add_exception_handler(Exception, errors.handle_unhandled_exception)

    @app.middleware("http")
    async def add_trace_id(request: Request, call_next):  # type: ignore[no-untyped-def]
        """Inject a deterministic trace_id so tests can assert on it."""
        request.state.trace_id = "trace-xyz"
        return await call_next(request)

    @app.post("/validation")
    async def validation_route(body: Payload) -> dict[str, Any]:  # type: ignore[no-untyped-def]
        """Route that triggers FastAPI/Pydantic validation."""
        return {"value": body.value}

    @app.get("/http-exc")
    async def http_exc_route() -> None:  # type: ignore[no-untyped-def]
        """Route that raises a FastAPI HTTPException."""
        raise HTTPException(status_code=404, detail="not found")

    @app.get("/unhandled")
    async def unhandled_route() -> None:  # type: ignore[no-untyped-def]
        """Route that raises an unhandled exception (mapped to 500)."""
        raise RuntimeError("boom")

    return app


def test_handle_validation_error_envelope_and_trace_id() -> None:
    """422 validation errors should be wrapped in the standard error envelope."""
    app = _make_app_with_handlers()
    client = TestClient(app)

    resp = client.post("/validation", json={"value": "not-an-int"})

    assert resp.status_code == 422
    body = resp.json()
    err = body["error"]
    assert err["code"] == "VALIDATION_ERROR"
    assert err["http_status"] == 422
    assert "Request validation failed" in err["message"]
    assert "errors" in err["details"]
    assert err["trace_id"] == "trace-xyz"


def test_handle_http_exception_envelope() -> None:
    """HTTPException should be mapped into the standardized error envelope."""
    app = _make_app_with_handlers()
    client = TestClient(app)

    resp = client.get("/http-exc")

    assert resp.status_code == 404
    body = resp.json()
    err = body["error"]
    assert err["code"] == "HTTP_ERROR"
    assert err["http_status"] == 404
    assert err["message"] == "not found"
    assert err["trace_id"] == "trace-xyz"


def test_handle_unhandled_exception_envelope() -> None:
    """Unhandled exceptions should be surfaced as INTERNAL_ERROR envelopes."""
    app = _make_app_with_handlers()
    # Important: don't re-raise server exceptions, we want the 500 response
    client = TestClient(app, raise_server_exceptions=False)

    resp = client.get("/unhandled")

    assert resp.status_code == 500
    body = resp.json()
    err = body["error"]
    assert err["code"] == "INTERNAL_ERROR"
    assert err["http_status"] == 500
    assert "Internal server error" in err["message"]
    assert err["trace_id"] == "trace-xyz"
