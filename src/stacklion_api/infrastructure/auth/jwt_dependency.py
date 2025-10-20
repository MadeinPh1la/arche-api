from __future__ import annotations

from collections.abc import Awaitable, Callable, Mapping, Sequence
from dataclasses import dataclass
from typing import Any

from fastapi import Depends, HTTPException, Request, status

from stacklion_api.config.features.auth import AuthSettings, get_auth_settings


@dataclass(frozen=True)
class Principal:
    """Authenticated principal extracted from a verified JWT.

    Attributes:
        sub: Subject claim (user identifier).
        scopes: Tuple of granted scopes.
        claims: Full claims mapping for downstream uses/auditing.
    """

    sub: str
    scopes: tuple[str, ...]
    claims: Mapping[str, Any]


def _extract_bearer_token(request: Request) -> str:
    """Extract the bearer token from the Authorization header."""
    auth = request.headers.get("Authorization") or ""
    if not auth.lower().startswith("bearer "):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Missing or invalid Authorization header",
        )
    return auth.split(" ", 1)[1].strip()


def _decode_hs256(token: str, cfg: AuthSettings) -> Mapping[str, Any]:
    """Decode & validate a JWT signed with HS256."""
    try:
        import jwt  # PyJWT
    except Exception as exc:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Auth unavailable (PyJWT not installed)",
        ) from exc

    if not cfg.hs256_secret:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Auth misconfigured (missing HS256 secret)",
        )

    try:
        return jwt.decode(
            token, cfg.hs256_secret, algorithms=["HS256"], options={"verify_aud": False}
        )
    except Exception as exc:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid or unverifiable token",
        ) from exc


def auth_required(
    required_scopes: Sequence[str] | None = None,
) -> Callable[[Request, AuthSettings], Awaitable[Principal]]:
    """Create a dependency that enforces authentication and optional scope checks."""

    async def _dep(
        request: Request,
        cfg: AuthSettings = Depends(get_auth_settings),
    ) -> Principal:
        if not cfg.enabled:
            return Principal(sub="dev-user", scopes=tuple(), claims={})

        token = _extract_bearer_token(request)
        claims = _decode_hs256(token, cfg)

        sub = str(claims.get("sub", ""))
        raw_scopes = claims.get("scopes", claims.get("scope", ""))
        if isinstance(raw_scopes, str):
            scope_list = [s.strip() for s in raw_scopes.split() if s.strip()]
        elif isinstance(raw_scopes, (list, tuple)):
            scope_list = [str(s).strip() for s in raw_scopes if str(s).strip()]
        else:
            scope_list = []
        scopes = tuple(scope_list)

        if required_scopes:
            missing = [s for s in required_scopes if s not in scopes]
            if missing:
                raise HTTPException(
                    status_code=status.HTTP_403_FORBIDDEN,
                    detail=f"Missing required scopes: {', '.join(missing)}",
                )

        return Principal(sub=sub, scopes=scopes, claims=claims)

    return _dep
