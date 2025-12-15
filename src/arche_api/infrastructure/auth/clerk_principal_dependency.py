# src/arche_api/infrastructure/auth/clerk_principal_dependency.py
"""Clerk Principal Dependency (Infrastructure Layer).

Purpose:
    Authenticate requests via Clerk-issued JWTs and return a typed `Principal`
    (adapter- and application-friendly identity) for routers/controllers.

Design:
    - Enforces Bearer token contract at the adapter boundary.
    - Verifies the token with a JWKS client and minimal claim checks.
    - Returns a small `Principal` value object, not raw claims.

Security:
    - Logs verification failures with structured context.
    - Avoids PII; only stable technical identifiers are propagated.

Layer:
    infrastructure/auth
"""

from __future__ import annotations

from typing import Annotated, Any

from fastapi import Depends, Header, HTTPException, status

from arche_api.config.settings import Settings, get_settings
from arche_api.domain.value_objects import Principal
from arche_api.infrastructure.logging.logger import get_json_logger
from arche_api.infrastructure.security.clerk_jwks import (
    ClerkJWKSClient,
    verify_clerk_token,
)

logger = get_json_logger(__name__)


async def require_clerk_principal(
    authorization: Annotated[str | None, Header(None, convert_underscores=False)],
    settings: Annotated[Settings, Depends(get_settings)],
) -> Principal:
    """Authenticate a request via Clerk JWT and return a `Principal`.

    Args:
        authorization: `Authorization` header (expected: ``Bearer <token>``).
        settings: Application settings injected via FastAPI dependency.

    Returns:
        Principal: Authenticated actor mapped from token claims.

    Raises:
        HTTPException: 401 for missing/invalid credentials; 403 if account is blocked.
    """
    if not authorization or not authorization.startswith("Bearer "):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Missing bearer token",
        )

    token: str = authorization.split(" ", 1)[1].strip()
    jwks = ClerkJWKSClient(
        issuer=str(settings.clerk_issuer),
        ttl_seconds=settings.clerk_jwks_ttl_seconds,
    )

    # Build verify_clerk_token kwargs so we only pass audience when present.
    verify_kwargs: dict[str, Any] = {
        "token": token,
        "jwks_client": jwks,
        "issuer": str(settings.clerk_issuer),
    }
    if settings.clerk_audience is not None:
        verify_kwargs["audience"] = settings.clerk_audience

    try:
        claims: dict[str, Any] = await verify_clerk_token(**verify_kwargs)
    except Exception as exc:
        logger.warning("jwt_verification_failed", extra={"reason": str(exc)})
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid or expired token",
        ) from exc

    subject: str | None = claims.get("sub")
    email: str | None = claims.get("email") or claims.get("primary_email")
    roles_claim = claims.get("roles") or claims.get("org_roles") or []
    roles: list[str] = list(roles_claim) if isinstance(roles_claim, list) else []

    if claims.get("blocked") is True:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Account is blocked",
        )

    principal = Principal(subject=subject, email=email, roles=roles)
    logger.debug(
        "authenticated_principal",
        extra={"subject": subject, "email_present": bool(email), "roles_count": len(roles)},
    )
    return principal
