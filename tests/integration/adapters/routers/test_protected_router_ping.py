# Copyright (c) Stacklion.
# SPDX-License-Identifier: MIT
"""Integration test for /v1/protected/ping."""

from __future__ import annotations

from fastapi.testclient import TestClient

from stacklion_api.main import create_app


def test_protected_ping_returns_ok_payload() -> None:
    app = create_app()
    client = TestClient(app)
    resp = client.get("/v1/protected/ping")

    assert resp.status_code == 200
    assert resp.json() == {"status": "ok"}
