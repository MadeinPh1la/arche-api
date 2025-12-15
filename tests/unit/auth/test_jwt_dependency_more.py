from types import SimpleNamespace

import pytest
from fastapi import HTTPException

from arche_api.infrastructure.auth.jwt_dependency import _decode_hs256


class _Cfg:
    enabled = True
    hs256_secret = ""  # triggers config error


def test_decode_hs256_missing_secret_raises_500():
    with pytest.raises(HTTPException) as ex:
        _decode_hs256("tok", _Cfg())
    assert ex.value.status_code == 500


def test_extract_bearer_token_messages():
    from arche_api.infrastructure.auth.jwt_dependency import _extract_bearer_token

    class Req(SimpleNamespace):
        headers = {}

    # missing header entirely
    with pytest.raises(HTTPException) as ex:
        _extract_bearer_token(Req())
    assert ex.value.detail == "Missing bearer token"

    # header present but no token after the prefix → your code returns same message
    r2 = Req()
    r2.headers = {"Authorization": "Bearer "}
    with pytest.raises(HTTPException) as ex2:
        _extract_bearer_token(r2)
    assert ex2.value.detail == "Missing bearer token"
