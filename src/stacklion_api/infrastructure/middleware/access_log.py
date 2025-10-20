# Copyright (c) Stacklion.
# SPDX-License-Identifier: MIT
"""
Access Log Middleware.

Summary:
    Emits a structured access log entry for every request/response pair with a
    minimal, high-signal field set suitable for JSON log ingestion and query.

Design:
    * Uses monotonic timing for latency measurement.
    * Pulls a request ID from `request.state.request_id` if a request-ID
      middleware executed earlier in the chain.
    * Keeps the payload small — deep payload logging belongs at the edge.

Fields:
    evt: Literal "access" marker.
    method: HTTP method.
    path: URL path (no scheme/host).
    query: Raw query string (no parsing here).
    status: HTTP status code (500 if unhandled exception).
    elapsed_ms: Latency in milliseconds, rounded to two decimals.
    client_ip: Best-effort client IP (from connection).
    request_id: Correlation ID if present.
    ok: True if the downstream handler returned normally; False if raised.

Usage:
    app.add_middleware(AccessLogMiddleware)
"""

from __future__ import annotations

import logging
import time
from typing import Any

from fastapi import Request
from starlette.middleware.base import BaseHTTPMiddleware, RequestResponseEndpoint
from starlette.responses import Response

# Central logger: use project logger if available, otherwise stdlib logger.
try:  # pragma: no cover - import safety
    from stacklion_api.infrastructure.logging import (
        logger as _logmod,
    )
except Exception:  # pragma: no cover - import safety
    _logmod = None  # type: ignore[assignment]

_get_json_logger = getattr(_logmod, "get_json_logger", None)
_logger: logging.Logger = (
    _get_json_logger(__name__) if callable(_get_json_logger) else logging.getLogger(__name__)
)


class AccessLogMiddleware(BaseHTTPMiddleware):
    """Structured access logging middleware."""

    async def dispatch(self, request: Request, call_next: RequestResponseEndpoint) -> Response:
        """Log a single access record around the downstream handler.

        Args:
            request: Incoming HTTP request.
            call_next: Next handler in the ASGI chain.

        Returns:
            Response: The downstream response.

        Raises:
            Exception: Re-raised after logging if the downstream handler fails.
        """
        t0 = time.perf_counter()
        response: Response | None = None
        ok = False
        try:
            response = await call_next(request)
            ok = True
            return response
        finally:
            elapsed_ms = (time.perf_counter() - t0) * 1000.0
            status_code = response.status_code if response is not None else 500
            log: dict[str, Any] = {
                "evt": "access",
                "method": request.method,
                "path": request.url.path,
                "query": str(request.url.query),
                "status": status_code,
                "elapsed_ms": round(elapsed_ms, 2),
                "client_ip": request.client.host if request.client else None,
                "request_id": getattr(getattr(request, "state", object()), "request_id", None),
                "ok": ok,
            }
            _logger.info("access_log", extra=log)
