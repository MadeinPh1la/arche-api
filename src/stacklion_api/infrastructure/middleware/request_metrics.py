# src/stacklion_api/infrastructure/middleware/request_metrics.py
# Copyright (c) Stacklion.
# SPDX-License-Identifier: MIT
"""
Request Latency Middleware (OpenTelemetry Histogram).

Summary:
    Starlette/FastAPI middleware that measures per-request latency and records
    it to an OTEL histogram named `http_server_request_duration_seconds`. The
    middleware attributes include HTTP method, templated route, and status code,
    making it straightforward to chart P50/P95 latencies in Grafana.

Design:
    - Uses the process-wide OTEL meter to lazily create a histogram instrument.
    - Records latency in a `finally` block so failures still produce samples.
    - Compatible with Starlette’s `BaseHTTPMiddleware` typing expectations
      across versions by annotating `call_next` as a generic async callable.

Usage:
    app.add_middleware(RequestLatencyMiddleware)
"""

from __future__ import annotations

import time
from collections.abc import Awaitable, Callable
from typing import Any

from opentelemetry import metrics
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import Response

__all__ = ["RequestLatencyMiddleware"]

_METER = metrics.get_meter("stacklion.request")
_LATENCY_HIST: Any | None = None  # OTEL histogram type is intentionally loose


def _hist() -> Any:
    """Return the process-wide HTTP server latency histogram.

    Returns:
        A lazily-created OpenTelemetry histogram instrument. The concrete type
        depends on the configured OTEL SDK/exporter and is treated as `Any`.
    """
    global _LATENCY_HIST
    if _LATENCY_HIST is None:
        _LATENCY_HIST = _METER.create_histogram(
            name="http_server_request_duration_seconds",
            description="Inbound request latency.",
            unit="s",
        )
    return _LATENCY_HIST


class RequestLatencyMiddleware(BaseHTTPMiddleware):
    """Middleware that records request latency to an OTEL histogram.

    The histogram follows a Prometheus-friendly naming convention so it can be
    scraped and visualized in Grafana (e.g., P50/P95 per route).
    """

    async def dispatch(
        self,
        request: Request,
        call_next: Callable[[Request], Awaitable[Response]],
    ) -> Response:
        """Measure and record latency for each inbound HTTP request.

        Args:
            request: Incoming Starlette/FastAPI request.
            call_next: The next handler in the ASGI chain.

        Returns:
            The downstream response produced by the application.

        Raises:
            Exception: Re-raises any exception from downstream handlers after
                recording a latency sample with a 500 status code.
        """
        start = time.perf_counter()
        status_code = 500  # pessimistic default for error paths
        try:
            response = await call_next(request)
            status_code = response.status_code
            return response
        finally:
            duration = time.perf_counter() - start
            route_obj = request.scope.get("route")
            route = (
                getattr(route_obj, "path_format", None)
                or getattr(route_obj, "path", None)
                or request.url.path
            )
            _hist().record(
                duration,
                attributes={
                    "http.method": request.method,
                    "http.route": route,
                    "http.status_code": status_code,
                },
            )
