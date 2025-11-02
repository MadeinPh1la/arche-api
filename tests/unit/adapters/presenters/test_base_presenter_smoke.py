from stacklion_api.adapters.presenters.base_presenter import BasePresenter


def test_present_success_and_error_smoke():
    p = BasePresenter[dict[str, str]]()

    # Success path
    ok = p.present_success(data={"status": "ok"})
    assert hasattr(ok, "body")
    assert getattr(ok.body, "data", None) == {"status": "ok"}

    # Error path
    err = p.present_error(code="BAD_REQUEST", http_status=400, message="oops", trace_id="t1")
    assert hasattr(err, "body")
    assert getattr(err.body, "error", None) is not None
    assert err.body.error.code == "BAD_REQUEST"
    assert err.body.error.message == "oops"
