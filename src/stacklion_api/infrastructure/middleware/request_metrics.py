# src/stacklion_api/infrastructure/middleware/request_metrics.py
# Copyright (c) Stacklion.
# SPDX-License-Identifier: MIT
"""Request Latency Middleware (OTEL + Prometheus, OTEL optional).

Summary:
    Measures server-side request latency and records to:
      • OpenTelemetry histogram: `http_server_request_duration_seconds` (optional)
      • Prometheus histogram:    `http_server_request_duration_seconds_bucket`
    Both instruments are created lazily and reused to avoid duplicate
    registration during hot reloads or cold-start tests.

Design:
    * Labels: (method, handler, status). Handler prefers templated route path.
    * Bounded buckets tuned for API latencies.
    * Errors in metrics code never impact request flow.
    * OpenTelemetry is a soft dependency: if not installed or disabled, we no-op.

Usage:
    export OTEL_ENABLED=true  # to enable OTEL when installed
    app.add_middleware(RequestLatencyMiddleware)
"""

from __future__ import annotations

import logging
import os
import time
from collections.abc import Awaitable, Callable
from typing import Any

# Third-party imports MUST be at the top to satisfy E402
from prometheus_client import REGISTRY, CollectorRegistry, Histogram
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import Response

__all__ = ["RequestLatencyMiddleware", "get_http_server_request_duration_seconds"]

logger = logging.getLogger(__name__)

# -----------------------------------------------------------------------------
# OpenTelemetry (soft dependency, lazy)
# -----------------------------------------------------------------------------
_OTEL_ENABLED = os.getenv("OTEL_ENABLED", "false").lower() in {"1", "true", "yes"}

try:
    # Soft dependency: may not be present in CI/dev.
    from opentelemetry import metrics as _otel_metrics

    _OTEL_AVAILABLE = True
except Exception:  # pragma: no cover - executed only when OTEL is missing
    _OTEL_AVAILABLE = False
    _otel_metrics = None

_OTEL_LATENCY_HIST: Any | None = None  # concrete type depends on SDK/exporter


class _NoopHistogram:
    """No-op substitute for OTEL histogram when OTEL is unavailable/disabled."""

    def record(self, *_: Any, **__: Any) -> None:
        return


def _otel_hist() -> Any:
    """Return the process-wide OTEL HTTP server latency histogram (or no-op)."""
    global _OTEL_LATENCY_HIST

    # If OTEL isn't installed or not enabled, always return a no-op histogram.
    if not (_OTEL_AVAILABLE and _OTEL_ENABLED):
        if _OTEL_LATENCY_HIST is None or not hasattr(_OTEL_LATENCY_HIST, "record"):
            _OTEL_LATENCY_HIST = _NoopHistogram()
        return _OTEL_LATENCY_HIST

    if _OTEL_LATENCY_HIST is None:
        try:
            meter = _otel_metrics.get_meter("stacklion.request")
            _OTEL_LATENCY_HIST = meter.create_histogram(
                name="http_server_request_duration_seconds",
                description="Inbound request latency.",
                unit="s",
            )
        except Exception:  # pragma: no cover (defensive)
            logger.debug("otel.create_histogram_failed", exc_info=True)
            _OTEL_LATENCY_HIST = _NoopHistogram()
    return _OTEL_LATENCY_HIST


# -----------------------------------------------------------------------------
# Prometheus (lazy/idempotent)
# -----------------------------------------------------------------------------
_BUCKETS = (0.005, 0.01, 0.025, 0.05, 0.1, 0.25, 0.5, 1.0, 2.5, 5.0, 10.0)
_SERVER_HIST: Histogram | None = None


def _registry() -> CollectorRegistry:
    return REGISTRY


def get_http_server_request_duration_seconds() -> Histogram:
    """Return the canonical server request-duration histogram (created once).

    Labels:
        method: Uppercased HTTP method.
        handler: Templated route or raw path.
        status: Response code as string.
    """
    global _SERVER_HIST
    if _SERVER_HIST is None:
        _SERVER_HIST = Histogram(
            "http_server_request_duration_seconds",
            "Request duration (seconds) — server-side histogram (canonical).",
            labelnames=("method", "handler", "status"),
            buckets=_BUCKETS,
            registry=_registry(),
        )
    return _SERVER_HIST


# -----------------------------------------------------------------------------
# Middleware
# -----------------------------------------------------------------------------
class RequestLatencyMiddleware(BaseHTTPMiddleware):
    """Record request latency to both Prometheus and (optionally) OpenTelemetry."""

    def __init__(self, app: Any) -> None:
        super().__init__(app)
        self._prom_hist = get_http_server_request_duration_seconds()

    async def dispatch(
        self,
        request: Request,
        call_next: Callable[[Request], Awaitable[Response]],
    ) -> Response:
        start = time.perf_counter()
        status_code = 500
        try:
            response = await call_next(request)
            status_code = response.status_code
            return response
        finally:
            duration = time.perf_counter() - start

            # Prefer templated route; fall back to raw path.
            route_obj = request.scope.get("route")
            handler = (
                getattr(route_obj, "path_format", None)
                or getattr(route_obj, "path", None)
                or request.url.path
            )

            try:
                self._prom_hist.labels(request.method.upper(), handler, str(status_code)).observe(
                    duration
                )
            except Exception:
                logger.debug("prom.histogram_observe_failed", exc_info=True)

            try:
                _otel_hist().record(
                    duration,
                    attributes={
                        "http.method": request.method,
                        "http.route": handler,
                        "http.target": request.url.path,
                        "http.status_code": status_code,
                    },
                )
            except Exception:
                logger.debug("otel.histogram_record_failed", exc_info=True)
