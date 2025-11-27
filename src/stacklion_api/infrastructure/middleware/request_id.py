# src/stacklion_api/infrastructure/middleware/request_id.py
# Copyright (c) Stacklion.
# SPDX-License-Identifier: MIT
"""Request ID Middleware.

Summary:
    Assigns a stable request correlation ID to each request and propagates it in
    the response headers. Uses an incoming `X-Request-ID` if present and valid;
    otherwise generates a new UUID4.

Contract:
    • Reads:  X-Request-ID (optional)
    • Writes: X-Request-ID (always written)
    • Stores: request.state.request_id (str)
    • Enriches logs via contextvars (request_id)

Notes:
    Keep the ID opaque; downstream systems (logs/metrics) should treat it as a
    correlation token only. Error envelopes should include this value as
    `trace_id` per EQS/DoD.
"""

from __future__ import annotations

import re
import uuid
from typing import Final

from fastapi import Request
from starlette.middleware.base import BaseHTTPMiddleware, RequestResponseEndpoint
from starlette.responses import Response

from stacklion_api.infrastructure.logging.logger import set_request_context

_REQUEST_ID_HEADER: Final[str] = "X-Request-ID"
_SAFE_RE: Final[re.Pattern[str]] = re.compile(r"^[A-Za-z0-9\-_.:@]{1,128}$")


def _coerce_request_id(raw: str | None) -> str:
    """Return a safe request id, preferring caller-provided values.

    Args:
        raw: Incoming request id header value, if any.

    Returns:
        Validated or generator-provided request id string.
    """
    if raw and _SAFE_RE.match(raw):
        return raw
    return str(uuid.uuid4())


class RequestIdMiddleware(BaseHTTPMiddleware):
    """Middleware that injects a stable request id onto the request and response."""

    async def dispatch(self, request: Request, call_next: RequestResponseEndpoint) -> Response:
        """Attach `request.state.request_id` and emit header on the response."""
        req_id = _coerce_request_id(request.headers.get(_REQUEST_ID_HEADER))

        # Expose on request.state for downstream logging/metrics/error envelopes.
        request.state.request_id = req_id

        # Enrich contextvars for structured logging.
        # TraceIdMiddleware may have already set a trace_id; we only touch request_id here.
        set_request_context(request_id=req_id)

        response: Response = await call_next(request)
        response.headers.setdefault(_REQUEST_ID_HEADER, req_id)
        return response
