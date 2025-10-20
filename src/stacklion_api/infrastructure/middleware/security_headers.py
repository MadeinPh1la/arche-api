# Copyright (c) Stacklion.
# SPDX-License-Identifier: MIT
"""
Security Headers Middleware (API-safe defaults)

Summary:
    Lightweight middleware that attaches a minimal, API-appropriate set of
    security headers to every response. It avoids HTML/CSP concerns and keeps
    defaults safe for JSON APIs, Swagger UI, and local development.

Headers set:
    X-Content-Type-Options: nosniff
    X-Frame-Options: DENY
    Referrer-Policy: no-referrer-when-downgrade
    Permissions-Policy: geolocation=()

Optional:
    Strict-Transport-Security (HSTS) can be enabled via the constructor.

Notes:
    • Do not enable HSTS on non-TLS/local environments.
    • If you need CSP, implement it at your edge for web UIs; APIs typically
      don’t render HTML and don’t need CSP here.
"""

from __future__ import annotations

from typing import Final

from fastapi import Request
from starlette.middleware.base import BaseHTTPMiddleware, RequestResponseEndpoint
from starlette.responses import Response
from starlette.types import ASGIApp

__all__ = ["SecurityHeadersMiddleware"]


class SecurityHeadersMiddleware(BaseHTTPMiddleware):
    """Attach a minimal set of security headers to every response.

    Args:
        app: The ASGI application.
        hsts_max_age: If > 0, also set `Strict-Transport-Security` with the given
            max-age (in seconds). Only enable this when serving strictly over HTTPS.
            Default is 0 (disabled).
        hsts_include_subdomains: Add `; includeSubDomains` to HSTS when enabled.
        hsts_preload: Add `; preload` to HSTS when enabled (requires meeting
            preload list requirements).

    The middleware uses `setdefault` so app/route-specific headers can override.
    """

    _BASE_HEADERS: Final[dict[str, str]] = {
        "X-Content-Type-Options": "nosniff",
        "X-Frame-Options": "DENY",
        "Referrer-Policy": "no-referrer-when-downgrade",
        "Permissions-Policy": "geolocation=()",
    }

    def __init__(
        self,
        app: ASGIApp,
        *,
        hsts_max_age: int = 0,
        hsts_include_subdomains: bool = False,
        hsts_preload: bool = False,
    ) -> None:
        super().__init__(app)
        self._hsts_max_age = int(hsts_max_age)
        self._hsts_include_subdomains = bool(hsts_include_subdomains)
        self._hsts_preload = bool(hsts_preload)

    async def dispatch(self, request: Request, call_next: RequestResponseEndpoint) -> Response:
        """Add headers after the downstream handler produces a response."""
        response: Response = await call_next(request)

        # Base headers
        for key, value in self._BASE_HEADERS.items():
            response.headers.setdefault(key, value)

        # Optional HSTS (only if explicitly enabled)
        if self._hsts_max_age > 0:
            parts = [f"max-age={self._hsts_max_age}"]
            if self._hsts_include_subdomains:
                parts.append("includeSubDomains")
            if self._hsts_preload:
                parts.append("preload")
            response.headers.setdefault("Strict-Transport-Security", "; ".join(parts))

        return response
