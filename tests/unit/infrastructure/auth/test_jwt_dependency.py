from __future__ import annotations

from collections.abc import Mapping

import pytest
from fastapi import HTTPException

import stacklion_api.infrastructure.auth.jwt_dependency as jwt_dep
from stacklion_api.config.features.auth import AuthSettings
from stacklion_api.infrastructure.auth.jwt_dependency import Principal, auth_required


class DummyRequest:
    """Minimal request-like object exposing headers mapping."""

    def __init__(self, headers: Mapping[str, str] | None = None) -> None:
        self.headers = dict(headers or {})


@pytest.mark.anyio
async def test_auth_required_returns_dev_principal_when_disabled() -> None:
    """When auth is disabled (default config), dependency should bypass JWT and return a dev principal."""
    dep = auth_required()
    principal = await dep(DummyRequest())

    assert isinstance(principal, Principal)
    assert principal.sub == "dev-user"
    assert principal.scopes == ()
    assert principal.claims == {}


def test_extract_bearer_token_missing_header_401() -> None:
    """No Authorization header -> 401 Missing bearer token."""
    req = DummyRequest(headers={})

    with pytest.raises(HTTPException) as info:
        jwt_dep._extract_bearer_token(req)

    err = info.value
    assert err.status_code == 401
    assert err.detail == "Missing bearer token"


def test_extract_bearer_token_empty_token_treated_as_missing_header() -> None:
    """'Bearer   ' is treated as a missing bearer token by the implementation."""
    req = DummyRequest(headers={"Authorization": "Bearer   "})

    with pytest.raises(HTTPException) as info:
        jwt_dep._extract_bearer_token(req)

    err = info.value
    assert err.status_code == 401
    assert err.detail == "Missing bearer token"


def test_extract_bearer_token_from_header_string() -> None:
    """Raw header string should be accepted and token extracted correctly."""
    token = jwt_dep._extract_bearer_token("Bearer abc123")
    assert token == "abc123"  # noqa: S105


def test_decode_hs256_missing_secret_raises_500() -> None:
    """_decode_hs256 should fail fast when secret is missing."""
    cfg = AuthSettings(enabled=True, hs256_secret=None)

    with pytest.raises(HTTPException) as info:
        jwt_dep._decode_hs256("token", cfg)  # noqa: S105

    err = info.value
    assert err.status_code == 500
    assert "misconfigured" in err.detail.lower()


def test_decode_hs256_invalid_token_raises_401() -> None:
    """Invalid JWT string should surface as 401 Invalid token."""
    cfg = AuthSettings(enabled=True, hs256_secret="secret")  # noqa: S106

    with pytest.raises(HTTPException) as info:
        jwt_dep._decode_hs256("not-a-jwt", cfg)  # noqa: S105

    err = info.value
    assert err.status_code == 401
    assert err.detail == "Invalid token"
