# Copyright (c) Arche.
# SPDX-License-Identifier: MIT
"""Unit tests for RequestIdMiddleware behavior and header rules."""

from __future__ import annotations

from fastapi import FastAPI, Request
from fastapi.testclient import TestClient

from arche_api.infrastructure.middleware.request_id import (
    _REQUEST_ID_HEADER,
    _SAFE_RE,
    RequestIdMiddleware,
)


def test_middleware_generates_uuid_and_sets_state_and_header() -> None:
    app = FastAPI()
    app.add_middleware(RequestIdMiddleware)

    @app.get("/echo")
    def echo(request: Request):
        # Ensure state is set by the middleware
        return {"rid": getattr(request.state, "request_id", None)}

    client = TestClient(app)
    r = client.get("/echo")

    assert r.status_code == 200
    data = r.json()
    rid = data["rid"]
    # Response header present via setdefault
    assert r.headers.get(_REQUEST_ID_HEADER) == rid
    # Matches SAFE_RE pattern
    assert _SAFE_RE.match(rid)


def test_middleware_uses_valid_incoming_and_rejects_invalid() -> None:
    app = FastAPI()
    app.add_middleware(RequestIdMiddleware)

    @app.get("/id")
    def get_id(request: Request):
        return {"rid": getattr(request.state, "request_id", None)}

    client = TestClient(app)

    # Valid incoming id is preserved
    valid = "abc-123_456:@Z"
    r1 = client.get("/id", headers={_REQUEST_ID_HEADER: valid})
    assert r1.status_code == 200
    assert r1.json()["rid"] == valid
    assert r1.headers.get(_REQUEST_ID_HEADER) == valid

    # Invalid incoming id (contains space) → replaced by generated
    invalid = "bad id with space"
    r2 = client.get("/id", headers={_REQUEST_ID_HEADER: invalid})
    gen = r2.headers.get(_REQUEST_ID_HEADER)
    assert gen and gen != invalid
    assert _SAFE_RE.match(gen)
