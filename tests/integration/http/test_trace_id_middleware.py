# tests/integration/http/test_trace_id_middleware.py
from fastapi.testclient import TestClient

from stacklion_api.main import create_app


def test_trace_is_generated_and_echoed():
    c = TestClient(create_app())
    r = c.get("/health/z")
    assert r.status_code == 200
    assert "x-trace-id" in r.headers
    assert r.headers["x-trace-id"]


def test_inbound_trace_is_reused_and_echoed():
    c = TestClient(create_app())
    hdr = {"x-trace-id": "test-123"}
    r = c.get("/health/z", headers=hdr)
    assert r.headers.get("x-trace-id") == "test-123"


def test_inbound_trace_is_trimmed_and_capped():
    from fastapi.testclient import TestClient

    from stacklion_api.main import create_app

    c = TestClient(create_app())
    # long value gets rejected -> new UUID generated (length != len(long))
    too_long = "x" * 129
    r = c.get("/health/z", headers={"x-trace-id": too_long})
    assert r.status_code == 200
    assert r.headers["x-trace-id"] != too_long  # replaced

    # whitespace-trimmed value is reused
    r2 = c.get("/health/z", headers={"x-trace-id": "  trim-me  "})
    assert r2.headers["x-trace-id"] == "trim-me"
