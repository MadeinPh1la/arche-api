from fastapi import Response

from arche_api.adapters.presenters.base_presenter import BasePresenter


def test_present_paginated_uses_explicit_etag_and_sets_headers():
    p = BasePresenter[dict[str, str]]()
    # Provide an explicit ETag so the compute path is bypassed
    pr = p.present_paginated(
        items=[{"i": 1}],
        page=1,
        page_size=50,
        total=1,
        trace_id="t-1",
        etag='"fixed-etag"',
    )
    # apply headers to a real Response
    r = Response()
    p.apply_headers(pr, r)
    assert r.headers.get("X-Request-ID") == "t-1"
    assert r.headers.get("ETag") == '"fixed-etag"'
