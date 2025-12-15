# Copyright (c) Arche.
# SPDX-License-Identifier: MIT
"""In-memory Rate Limit Middleware (token bucket, dev/local only)

Summary:
    A lightweight token-bucket limiter suitable for development and CI. It
    tracks tokens per (client_ip, path) key in process memory and emits
    standard rate limit headers.

Emitted headers:
    X-RateLimit-Limit, X-RateLimit-Remaining, X-RateLimit-Reset, Retry-After (on 429)
"""

from __future__ import annotations

import time
from dataclasses import dataclass

from fastapi import Request
from starlette import status
from starlette.middleware.base import BaseHTTPMiddleware, RequestResponseEndpoint
from starlette.responses import JSONResponse, Response
from starlette.types import ASGIApp


@dataclass
class _Bucket:
    """Token bucket state."""

    tokens: float
    last: float


class RateLimitMiddleware(BaseHTTPMiddleware):
    """Very simple in-memory token bucket for dev/local.

    Args:
        app: ASGI application.
        rate_per_sec: Token refill rate per second.
        burst: Maximum bucket capacity (requests allowed at once).
    """

    def __init__(self, app: ASGIApp, rate_per_sec: float = 5.0, burst: int = 10) -> None:
        super().__init__(app)
        self.rate: float = float(rate_per_sec)
        self.capacity: float = float(burst)
        self.buckets: dict[str, _Bucket] = {}

    def _key(self, request: Request) -> str:
        """Return a per-client, per-path key."""
        ip = request.client.host if request.client else "unknown"
        return f"{ip}:{request.url.path}"

    async def dispatch(self, request: Request, call_next: RequestResponseEndpoint) -> Response:
        """Apply token-bucket limiting and annotate responses with standard headers."""
        now = time.monotonic()
        key = self._key(request)
        bucket = self.buckets.get(key)
        if bucket is None:
            bucket = _Bucket(tokens=self.capacity, last=now)
            self.buckets[key] = bucket

        # Refill
        delta = max(0.0, now - bucket.last)
        bucket.tokens = min(self.capacity, bucket.tokens + delta * self.rate)
        bucket.last = now

        # Try to consume a token
        if bucket.tokens < 1.0:
            retry_after = max(1, int((1.0 - bucket.tokens) / self.rate) + 1)
            limited = JSONResponse(
                status_code=status.HTTP_429_TOO_MANY_REQUESTS,
                content={
                    "error": {
                        "code": "RATE_LIMITED",
                        "http_status": 429,
                        "message": "Too many requests",
                    }
                },
            )
            limited.headers.update(
                {
                    "Retry-After": str(retry_after),
                    "X-RateLimit-Limit": str(int(self.capacity)),
                    "X-RateLimit-Remaining": "0",
                    "X-RateLimit-Reset": str(retry_after),
                }
            )
            return limited

        # Spend one token before calling downstream
        bucket.tokens -= 1.0
        self.buckets[key] = bucket

        response: Response = await call_next(request)

        # After response, expose headers with current remaining tokens
        response.headers.update(
            {
                "X-RateLimit-Limit": str(int(self.capacity)),
                "X-RateLimit-Remaining": str(int(bucket.tokens)),
                "X-RateLimit-Reset": "0",
            }
        )
        return response
