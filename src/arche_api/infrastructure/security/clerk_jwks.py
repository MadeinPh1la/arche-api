from __future__ import annotations

import time
from dataclasses import dataclass
from typing import Any

import httpx
from jose import jwk, jwt
from jose.utils import base64url_decode

from arche_api.infrastructure.logging.logger import get_json_logger

logger = get_json_logger(__name__)


@dataclass(frozen=True)
class _CachedJWKS:
    """In-memory JWKS cache entry."""

    keys: dict[str, Any]
    expires_at: float


class ClerkJWKSClient:
    """Fetch and cache Clerk JWKS; verify JWT signatures (infrastructure-only).

    Attributes:
        issuer: OIDC issuer (e.g., https://<subdomain>.clerk.accounts.dev)
        ttl_seconds: In-memory JWKS cache TTL.
    """

    def __init__(self, issuer: str, ttl_seconds: int = 300) -> None:
        self._issuer = issuer.rstrip("/")
        self._jwks_url = f"{self._issuer}/.well-known/jwks.json"
        self._ttl_seconds = ttl_seconds
        self._cache: _CachedJWKS | None = None

    async def _get_jwks(self) -> dict[str, Any]:
        """Return a mapping of kid -> JWK, using a short-lived in-memory cache."""
        now = time.time()
        if self._cache and self._cache.expires_at > now:
            return self._cache.keys

        logger.debug("fetch_clerk_jwks", extra={"extra": {"jwks_url": self._jwks_url}})
        async with httpx.AsyncClient(timeout=5.0) as client:
            resp = await client.get(self._jwks_url)
            resp.raise_for_status()
            payload: dict[str, Any] = resp.json()

        keys: dict[str, Any] = {
            k["kid"]: k for k in payload.get("keys", []) if isinstance(k, dict) and "kid" in k
        }
        self._cache = _CachedJWKS(keys=keys, expires_at=now + self._ttl_seconds)
        logger.info(
            "clerk_jwks_cached",
            extra={"extra": {"key_count": len(keys), "ttl_seconds": self._ttl_seconds}},
        )
        return keys

    async def get_key_for_token(self, token: str) -> tuple[dict[str, Any], dict[str, Any]]:
        """Return `(jwk, unverified_header)` for the token's `kid`.

        Raises:
            KeyError: If header lacks `kid` or the `kid` is not in JWKS after a refresh.
            httpx.HTTPError: If JWKS retrieval fails.
            ValueError: If the token header is malformed.
        """
        try:
            unverified_header: dict[str, Any] = jwt.get_unverified_header(token)
        except Exception as exc:  # jose can raise on malformed tokens
            raise ValueError("Malformed JWT header") from exc

        kid = unverified_header.get("kid")
        if not isinstance(kid, str) or not kid:
            raise KeyError("Missing 'kid' in JWT header")

        keys = await self._get_jwks()
        if kid not in keys:
            # Force a one-time refresh in case of key rotation.
            self._cache = None
            keys = await self._get_jwks()
            if kid not in keys:
                raise KeyError(f"Unknown 'kid': {kid}")

        return keys[kid], unverified_header

    @staticmethod
    def verify_signature(token: str, key_data: dict[str, Any]) -> None:
        """Verify the JWS signature using the provided JWK.

        Raises:
            ValueError: If the token is malformed or the signature is invalid.
        """
        try:
            public_key = jwk.construct(key_data)
            # A well-formed JWS has exactly 3 segments (header.payload.signature).
            message, encoded_sig = token.rsplit(".", 1)
        except Exception as exc:
            raise ValueError("Malformed JWT structure") from exc

        decoded_sig = base64url_decode(encoded_sig.encode("utf-8"))
        if not public_key.verify(message.encode("utf-8"), decoded_sig):
            raise ValueError("Invalid token signature")


async def verify_clerk_token(
    *,
    token: str,
    jwks_client: ClerkJWKSClient,
    issuer: str,
    audience: str,
) -> dict[str, Any]:
    """Verify a Clerk JWT end-to-end (signature + claims).

    Args:
        token: Raw bearer token from the Authorization header.
        jwks_client: JWKS client used to resolve the signing key.
        issuer: Expected `iss` claim (string).
        audience: Expected `aud` claim (string).

    Returns:
        Decoded JWT claims.

    Raises:
        ValueError: For signature or claims errors.
        KeyError: When `kid` is missing/unknown.
        httpx.HTTPError: If JWKS cannot be fetched.
    """
    key_data, _ = await jwks_client.get_key_for_token(token)
    ClerkJWKSClient.verify_signature(token, key_data)

    # Verify claims (iss/aud/exp/nbf) with python-jose.
    alg = key_data.get("alg") or "RS256"
    if not isinstance(alg, str):
        alg = "RS256"

    claims: dict[str, Any] = jwt.decode(
        token,
        key=key_data,  # jose will handle JWK dicts
        algorithms=[alg],
        audience=audience,
        issuer=issuer,
        options={"verify_aud": True, "verify_iss": True, "verify_exp": True, "verify_nbf": True},
    )
    return claims
