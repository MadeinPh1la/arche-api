from __future__ import annotations

import jwt
import pytest
from fastapi import Depends, FastAPI
from fastapi.testclient import TestClient

from stacklion_api.infrastructure.auth.jwt_dependency import Principal, auth_required

# B008-safe default instance so FastAPI does not treat the handler param as a required body
_PRINCIPAL_DEFAULT = Principal()


def _app_with_scope(required_scope: str) -> FastAPI:
    app = FastAPI()
    dep = auth_required([required_scope])

    @app.get("/scope-check", dependencies=[Depends(dep)])
    def scope_check(_: Principal = _PRINCIPAL_DEFAULT) -> dict[str, str]:
        return {"ok": "yes"}

    return app


def _token(secret: str, *, scopes: str | None) -> str:
    claims: dict[str, object] = {"sub": "u1"}
    if scopes is not None:
        claims["scope"] = scopes  # space-delimited per our dep
    return jwt.encode(claims, secret, algorithm="HS256")


@pytest.mark.parametrize(
    "scopes, expected",
    [
        (None, 403),
        ("read:other", 403),
        ("read:secure", 200),
        ("read:secure write:other", 200),
    ],
)
def test_auth_required_scope(
    monkeypatch: pytest.MonkeyPatch, scopes: str | None, expected: int
) -> None:
    # enable auth with HS256 secret
    monkeypatch.setenv("AUTH_ENABLED", "true")
    monkeypatch.setenv("AUTH_HS256_SECRET", "t0psecret")

    app = _app_with_scope("read:secure")
    client = TestClient(app)

    tok = _token("t0psecret", scopes=scopes)
    r = client.get("/scope-check", headers={"Authorization": f"Bearer {tok}"})
    assert r.status_code == expected
