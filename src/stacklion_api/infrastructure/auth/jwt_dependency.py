# Copyright (c) Stacklion.
# SPDX-License-Identifier: MIT
"""JWT (HS256) Authentication Dependency.

Feature-flagged dependency that enforces bearer authentication when enabled.
Exact error messages are aligned with tests and API standards.

This module is framework-level and only concerns HTTP-adjacent auth plumbing.
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable, Iterable, Mapping
from typing import Any

from fastapi import HTTPException, Request
from pydantic import BaseModel, Field
from pydantic.config import ConfigDict

from stacklion_api.config.features.auth import AuthSettings, get_auth_settings


class Principal(BaseModel):
    """Authenticated principal extracted from a verified JWT.

    Attributes:
        sub: Subject claim (user identifier).
        scopes: Normalized scopes as a tuple.
        claims: Full claims mapping for downstream uses/auditing.
    """

    model_config = ConfigDict(frozen=True)  # keep immutability semantics

    sub: str = ""  # default so FastAPI can instantiate with no data
    scopes: tuple[str, ...] = ()  # default empty scopes
    claims: Mapping[str, Any] = Field(default_factory=dict)


def _extract_bearer_token(obj: Any) -> str:
    """Extract a bearer token from either a Request-like object or a raw header string.

    Produces the exact error messages asserted by tests:
    - "Missing bearer token" when header is absent/malformed
    - "Missing token" when the bearer value is empty

    Args:
        obj: Either a FastAPI/Starlette Request (or any object with a ``headers`` mapping),
            or a raw Authorization header string (e.g., "Bearer eyJhbGciOi...").

    Returns:
        str: Raw JWT token (no "Bearer " prefix).

    Raises:
        HTTPException: With 401 on missing/malformed header or empty token.
    """
    if hasattr(obj, "headers") and isinstance(getattr(obj, "headers", None), (dict, Mapping)):
        raw = obj.headers.get("Authorization")
    else:
        raw = obj  # assume string or None

    auth = (raw or "").strip()
    if not auth or not auth.lower().startswith("bearer "):
        raise HTTPException(status_code=401, detail="Missing bearer token")
    token = auth.split(" ", 1)[1].strip()
    if not token:
        raise HTTPException(status_code=401, detail="Missing token")
    return token


def _decode_hs256(token: str, cfg: AuthSettings) -> Mapping[str, Any]:
    """Decode and validate a JWT signed with HS256.

    Args:
        token: JWT token string.
        cfg: Authentication settings (secret, enablement flag).

    Returns:
        Mapping[str, Any]: Decoded claims.

    Raises:
        HTTPException: If decoding fails or configuration is invalid.
    """
    try:
        import jwt  # PyJWT
    except Exception as exc:
        raise HTTPException(
            status_code=500,
            detail="Auth unavailable (PyJWT not installed)",
        ) from exc

    if not cfg.hs256_secret:
        raise HTTPException(
            status_code=500,
            detail="Auth misconfigured (missing HS256 secret)",
        )

    try:
        return jwt.decode(
            token, cfg.hs256_secret, algorithms=["HS256"], options={"verify_aud": False}
        )
    except Exception as exc:
        # Exact message asserted by tests
        raise HTTPException(status_code=401, detail="Invalid token") from exc


def auth_required(
    required_scopes: str | Iterable[str] | None = None,
) -> Callable[..., Awaitable[Principal]]:
    """Create a dependency that enforces authentication and optional scope checks.

    Behavior is feature-flagged by ``AUTH_ENABLED``. When disabled, a synthetic
    dev principal is returned.
    """
    if isinstance(required_scopes, str):
        required: set[str] = {s for s in required_scopes.split() if s}
    else:
        required = set(required_scopes or ())

    async def _dep(request: Request) -> Principal:
        cfg = get_auth_settings()

        # Feature flag: when disabled, bypass auth with a synthetic principal.
        if not cfg.enabled:
            return Principal(sub="dev-user", scopes=tuple(), claims={})

        # Read the header *yourself* from Request; no FastAPI header params means no 422.
        token = _extract_bearer_token(request)
        claims = _decode_hs256(token, cfg)

        sub = str(claims.get("sub", ""))

        raw_scopes = claims.get("scopes", claims.get("scope", ""))
        if isinstance(raw_scopes, str):
            scope_set = {s for s in raw_scopes.split() if s}
        elif isinstance(raw_scopes, (list, tuple, set)):
            scope_set = {str(s) for s in raw_scopes if str(s)}
        else:
            scope_set = set()

        if required and not required.issubset(scope_set):
            raise HTTPException(status_code=403, detail="Forbidden")

        return Principal(sub=sub, scopes=tuple(sorted(scope_set)), claims=claims)

    return _dep
