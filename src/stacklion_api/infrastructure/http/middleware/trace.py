# src/stacklion_api/infrastructure/http/middleware/trace.py
# Copyright (c) Stacklion.
# SPDX-License-Identifier: MIT
"""Trace ID Middleware.

Summary:
    Starlette/FastAPI middleware that guarantees every request has a stable
    per-request correlation identifier and that the same value is echoed back
    to clients. The ID is exposed as the HTTP header ``x-trace-id`` and also
    attached to ``request.state.trace_id`` for downstream access (routers,
    dependencies, exception handlers, logging).

Design:
    * Idempotent: if the inbound request already includes ``x-trace-id`` and
      it is non-empty, we reuse it; otherwise a new UUIDv4 is generated.
    * Side-effect free: no I/O; header parsing is purely synchronous.
    * Defensive: trims/validates the inbound value; falls back to a fresh UUID
      if the supplied value is unusable.
    * Logging integration: stores the trace id in a contextvar so structured
      logs automatically include ``trace_id``.

Security & Audit:
    * The trace id is a client-visible correlation token (not a secret).
    * Do not embed PII or secrets in the trace id.
    * Log pipelines should include this header to correlate spans/lines.

Layer:
    infrastructure/http/middleware
"""

from __future__ import annotations

import uuid
from collections.abc import Awaitable, Callable

from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import Response

from stacklion_api.infrastructure.logging.logger import set_request_context

# Public, lowercase header name (HTTP headers are case-insensitive).
TRACE_HEADER = "x-trace-id"

# Hard cap to avoid pathological header sizes; typical UUIDs are 36 chars.
_MAX_TRACE_LEN = 128


def _sanitize_inbound_trace(raw: str | None) -> str | None:
    """Return a safe, non-empty trace id if provided; otherwise ``None``.

    Rules:
        * Trim surrounding whitespace.
        * Reject empty/whitespace-only after trim.
        * Reject values longer than `_MAX_TRACE_LEN`.
        * Accept any non-empty string; if you want to enforce UUID-only,
          do it upstream in an API gateway.

    Args:
        raw: Inbound value from request headers (may be ``None``).

    Returns:
        Sanitized string or ``None`` if invalid/unusable.
    """
    if raw is None:
        return None
    value = raw.strip()
    if not value:
        return None
    if len(value) > _MAX_TRACE_LEN:
        return None
    return value


def _new_trace_id() -> str:
    """Return a new UUIDv4 string, always lowercase."""
    return str(uuid.uuid4())


class TraceIdMiddleware(BaseHTTPMiddleware):
    """Attach/echo a correlation id for every request.

    Behavior:
        * On request:
            - Inspect ``x-trace-id`` header; if present and sane, reuse it.
            - Otherwise, generate a fresh UUIDv4.
            - Persist on ``request.state.trace_id`` for downstream access.
            - Store in a contextvar for log enrichment.
        * On response:
            - Echo the final trace id on the ``x-trace-id`` response header.

    This middleware is safe to stack with access-log, metrics, or error
    handlers; ensure it is added *before* handlers that read ``trace_id``.
    """

    async def dispatch(
        self,
        request: Request,
        call_next: Callable[[Request], Awaitable[Response]],
    ) -> Response:
        """Attach the trace id to the request/response cycle."""
        inbound = request.headers.get(TRACE_HEADER)
        trace_id = _sanitize_inbound_trace(inbound) or _new_trace_id()

        # Expose to downstream code (routers/deps/handlers) and logging.
        request.state.trace_id = trace_id
        set_request_context(trace_id=trace_id)

        response = await call_next(request)

        # Echo to client for correlation; do not overwrite if downstream set it.
        if TRACE_HEADER not in response.headers:
            response.headers[TRACE_HEADER] = trace_id
        return response


__all__ = [
    "TRACE_HEADER",
    "TraceIdMiddleware",
]
