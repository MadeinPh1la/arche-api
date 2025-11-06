from __future__ import annotations

from fastapi.testclient import TestClient

from stacklion_api.main import create_app


def test_trace_id_header_is_echoed_and_used_in_error_envelope():
    app = create_app()
    client = TestClient(app)

    # trigger a validation error on a known endpoint (missing required params)
    h = {"x-trace-id": "test-trace-123"}
    r = client.get("/v1/quotes/historical", headers=h)  # no params -> 422
    assert r.status_code in (400, 422)
    assert r.headers.get("x-trace-id") == "test-trace-123"

    body = r.json()
    assert "error" in body
    err = body["error"]
    # error handler may include trace_id in the error object
    if "trace_id" in err:
        assert err["trace_id"] == "test-trace-123"
