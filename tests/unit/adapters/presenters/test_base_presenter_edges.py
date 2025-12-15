from fastapi import Response

from arche_api.adapters.presenters.base_presenter import BasePresenter


def test_present_success_applies_trace_and_emits_etag():
    p = BasePresenter[dict[str, str]]()

    # Build a Success envelope with a trace id (present_success computes an ETag by design)
    result = p.present_success(data={"x": "y"}, trace_id="req-123")

    # Apply headers to a real Starlette Response
    resp = Response()
    p.apply_headers(result, resp)

    # X-Request-ID should be echoed; ETag should be present (computed)
    assert resp.headers.get("X-Request-ID") == "req-123"
    assert "ETag" in resp.headers
    assert resp.headers["ETag"].startswith('"') and resp.headers["ETag"].endswith('"')


def test_present_error_applies_trace_and_has_no_etag():
    p = BasePresenter[dict[str, str]]()

    # Error path uses _standard_headers with etag=None
    result = p.present_error(
        code="INTERNAL_ERROR",
        http_status=500,
        message="boom",
        trace_id="trace-xyz",
    )

    resp = Response()
    p.apply_headers(result, resp)

    # Trace should be echoed; no ETag for errors
    assert resp.headers.get("X-Request-ID") == "trace-xyz"
    assert "ETag" not in resp.headers
