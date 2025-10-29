# src/stacklion_api/infrastructure/middleware/request_metrics.py
# Copyright (c) Stacklion.
# SPDX-License-Identifier: MIT
"""
Request Latency Middleware (OTEL + Prometheus histogram).

Summary:
    Starlette/FastAPI middleware that measures per-request latency and records:
      1) OpenTelemetry histogram: `http_server_request_duration_seconds`
      2) Prometheus histogram:   `http_server_request_duration_seconds_bucket`
         (labels: method, handler, status)

Design:
    - Uses the process-wide OTEL meter; lazily creates the histogram instrument.
    - Prometheus histogram is a module singleton, lazily created, to avoid
      duplicate registration across multiple app factories/tests.
    - Records in a `finally` block so failures still produce samples.
    - `handler` label prefers templated route (path_format/path) and falls back
      to raw path.

Usage:
    app.add_middleware(RequestLatencyMiddleware)
"""

from __future__ import annotations

import logging
import time
from collections.abc import Awaitable, Callable
from typing import Any

from opentelemetry import metrics
from prometheus_client import Histogram
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import Response

__all__ = ["RequestLatencyMiddleware"]

logger = logging.getLogger(__name__)

# ---------------------------
# OpenTelemetry (lazy meter)
# ---------------------------
_METER = metrics.get_meter("stacklion.request")
_OTEL_LATENCY_HIST: Any | None = None  # concrete type varies by SDK/exporter


def _otel_hist() -> Any:
    """Return the process-wide OTEL HTTP server latency histogram."""
    global _OTEL_LATENCY_HIST
    if _OTEL_LATENCY_HIST is None:
        _OTEL_LATENCY_HIST = _METER.create_histogram(
            name="http_server_request_duration_seconds",
            description="Inbound request latency.",
            unit="s",
        )
    return _OTEL_LATENCY_HIST


# ---------------------------
# Prometheus (canonical)
# ---------------------------
_BUCKETS = (0.005, 0.01, 0.025, 0.05, 0.1, 0.25, 0.5, 1, 2.5, 5, 10)
_PROM_SERVER_HIST: Histogram | None = None


def _prom_server_hist() -> Histogram:
    """Canonical server histogram: http_server_request_duration_seconds."""
    global _PROM_SERVER_HIST
    if _PROM_SERVER_HIST is None:
        _PROM_SERVER_HIST = Histogram(
            "http_server_request_duration_seconds",
            "Request duration (seconds) — server-side histogram (canonical).",
            labelnames=("method", "handler", "status"),
            buckets=_BUCKETS,
        )
    return _PROM_SERVER_HIST


class RequestLatencyMiddleware(BaseHTTPMiddleware):
    """Middleware that records request latency to OTEL and Prometheus histograms."""

    async def dispatch(
        self,
        request: Request,
        call_next: Callable[[Request], Awaitable[Response]],
    ) -> Response:
        """Measure and record latency for each inbound HTTP request."""
        start = time.perf_counter()
        status_code = 500  # pessimistic default for error paths
        try:
            response = await call_next(request)
            status_code = response.status_code
            return response
        finally:
            duration = time.perf_counter() - start

            # Prefer templated route for the "handler" label; fall back to raw path.
            route_obj = request.scope.get("route")
            handler = (
                getattr(route_obj, "path_format", None)
                or getattr(route_obj, "path", None)
                or request.url.path
            )
            raw_path = request.url.path  # useful for OTEL attributes

            # Prometheus (canonical)
            try:
                _prom_server_hist().labels(request.method, handler, str(status_code)).observe(
                    duration
                )
            except Exception:
                # Never let metrics break requests
                logger.debug("prom.histogram_observe_failed", exc_info=True)

            # OpenTelemetry
            try:
                _otel_hist().record(
                    duration,
                    attributes={
                        "http.method": request.method,
                        "http.route": handler,
                        "http.target": raw_path,
                        "http.status_code": status_code,
                    },
                )
            except Exception:
                logger.debug("otel.histogram_record_failed", exc_info=True)
