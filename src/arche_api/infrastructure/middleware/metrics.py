# Copyright (c)
# SPDX-License-Identifier: MIT
"""Prometheus request metrics middleware (lazy, idempotent collectors).

Starlette/FastAPI middleware that records per-request counters and latency
to Prometheus without registering collectors at import time. Collectors are
created via centralized registry-aware helpers and cached per active registry.

Design:
    * No import-time registration.
    * Low-cardinality labels: (method, status).
    * Bounded buckets for short request durations.
    * Never impacts request flow on collector/observe errors.

Exposed API:
    - PromMetricsMiddleware: Starlette middleware
    - get_http_requests_counter(): Counter singleton
    - get_http_request_latency_seconds(): Histogram singleton
"""

from __future__ import annotations

import logging
import time
from collections.abc import Awaitable, Callable
from typing import TYPE_CHECKING, Any

from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import Response

# Centralized helpers (no direct prometheus_client imports)
from arche_api.infrastructure.observability.metrics import (
    _get_or_create_counter,
    _get_or_create_hist,
)

if TYPE_CHECKING:  # typing-only imports
    from prometheus_client import Counter, Histogram

logger = logging.getLogger(__name__)

__all__ = [
    "PromMetricsMiddleware",
    "get_http_requests_counter",
    "get_http_request_latency_seconds",
]

# -----------------------------------------------------------------------------
# Lazy, idempotent collectors
# -----------------------------------------------------------------------------
_http_requests: Counter | None = None
_http_latency: Histogram | None = None


def get_http_requests_counter() -> Counter:
    """Return the global HTTP requests counter (created once).

    Labels:
        method: Uppercased HTTP method.
        status: Response status code as string.

    Returns:
        Counter: Registry-aware counter bound to the active registry.
    """
    global _http_requests
    if _http_requests is None:
        _http_requests = _get_or_create_counter(
            "http_requests",
            "Total HTTP requests by method and status",
            labelnames=("method", "status"),
        )
    return _http_requests


def get_http_request_latency_seconds() -> Histogram:
    """Return the global HTTP request latency histogram (created once).

    Labels:
        method: Uppercased HTTP method.
        status: Response status code as string.

    Returns:
        Histogram: Registry-aware histogram bound to the active registry.
    """
    global _http_latency
    if _http_latency is None:
        _http_latency = _get_or_create_hist(
            "http_request_latency_seconds",
            "HTTP request latency in seconds",
            labelnames=("method", "status"),
            buckets=(0.01, 0.025, 0.05, 0.1, 0.25, 0.5, 1.0, 2.5, 5.0, 10.0),
        )
    return _http_latency


# -----------------------------------------------------------------------------
# Middleware
# -----------------------------------------------------------------------------
class PromMetricsMiddleware(BaseHTTPMiddleware):
    """Record per-request counters and latency with lazy collectors.

    Notes:
        * Collectors are obtained/bound in ``__init__``; all requests reuse them.
        * No exceptions propagate from metrics recording.
    """

    def __init__(self, app: Any) -> None:
        """Initialize middleware and bind collectors."""
        super().__init__(app)
        self._requests = get_http_requests_counter()
        self._latency = get_http_request_latency_seconds()

    async def dispatch(
        self,
        request: Request,
        call_next: Callable[[Request], Awaitable[Response]],
    ) -> Response:
        """Record metrics for the request and return the response."""
        start = time.perf_counter()
        response = await call_next(request)
        elapsed = time.perf_counter() - start

        method = request.method.upper()
        status = str(response.status_code)

        try:
            self._requests.labels(method, status).inc()
            self._latency.labels(method, status).observe(elapsed)
        except Exception:
            # Never allow metrics to impact request flow.
            logger.debug("prom.metrics_record_failed", exc_info=True)

        return response
