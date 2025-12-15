from fastapi import Response

from arche_api.adapters.routers.base_router import BaseRouter
from arche_api.adapters.schemas.http.envelopes import SuccessEnvelope


def test_send_success_applies_headers_and_returns_mapping_copy():
    # PresentResult-like object with a plain mapping body and headers to apply
    class _Res:
        def __init__(self) -> None:
            self.headers = {"ETag": '"abc123"'}

    result = type(
        "PR", (), {"body": {"status": "ok"}, "headers": {"X-Request-ID": "r-1", "ETag": '"abc123"'}}
    )()
    resp = Response()
    out = BaseRouter.send_success(resp, result)
    # Headers applied
    assert resp.headers.get("X-Request-ID") == "r-1"
    assert resp.headers.get("ETag") == '"abc123"'
    # Body normalized to concrete dict (not the same object)
    assert out == {"status": "ok"}
    assert out is not result.body  # copy path (Mapping -> dict)


def test_send_success_returns_model_instance_unchanged_when_no_response():
    # When body is a Pydantic model, send_success should return the instance itself
    env = SuccessEnvelope[dict[str, str]](data={"k": "v"})
    result = type("PR", (), {"body": env, "headers": {}})()
    out = BaseRouter.send_success(None, result)
    assert out is env
