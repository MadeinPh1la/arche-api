# Copyright (c) Stacklion.
# SPDX-License-Identifier: MIT
"""Integration test: request-id header appears through the real app stack."""

from __future__ import annotations

from fastapi.testclient import TestClient

from stacklion_api.main import create_app


def test_request_id_header_on_protected_ping() -> None:
    app = create_app()
    client = TestClient(app)

    r = client.get("/v1/protected/ping")
    assert r.status_code == 200
    # The real app should set X-Request-ID
    assert "X-Request-ID" in r.headers
    assert r.headers["X-Request-ID"]
