# Copyright (c) Stacklion.
# SPDX-License-Identifier: MIT
"""
Prometheus Metrics Middleware.

Summary:
    Emits basic request/response metrics: total count and latency histogram.
    Uses the default Prometheus REGISTRY. Pair with `/metrics` router.

Notes:
    * Keep labels minimal to avoid high cardinality.
"""

from __future__ import annotations

import time

from fastapi import Request
from prometheus_client import Counter, Histogram
from starlette.middleware.base import BaseHTTPMiddleware, RequestResponseEndpoint
from starlette.responses import Response

_REQUESTS = Counter(
    "http_requests_total",
    "Total HTTP requests",
    ["method", "path", "status"],
)

_LATENCY = Histogram(
    "http_request_duration_seconds",
    "Request latency in seconds",
    ["method", "path", "status"],
)


class PromMetricsMiddleware(BaseHTTPMiddleware):
    """Prometheus metrics collection middleware."""

    async def dispatch(self, request: Request, call_next: RequestResponseEndpoint) -> Response:
        """Record request count and latency histogram with coarse labels."""
        t0 = time.perf_counter()
        response: Response | None = None
        try:
            response = await call_next(request)
            return response
        finally:
            status = str(getattr(response, "status_code", 500))
            method = request.method
            # Use the routed path if you prefer; here we use raw path to avoid router coupling.
            path = request.url.path

            _REQUESTS.labels(method=method, path=path, status=status).inc()
            _LATENCY.labels(method=method, path=path, status=status).observe(
                time.perf_counter() - t0
            )
