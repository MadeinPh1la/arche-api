# src/stacklion_api/adapters/routers/metrics_router.py
# Copyright (c) Stacklion.
# SPDX-License-Identifier: MIT
"""Prometheus scrape endpoint (`/metrics`).

This router exposes a text-format Prometheus endpoint and *warms* lazily
created histograms so that classic `_bucket`/`_count`/`_sum` series appear
on the very first scrape (cold start). In particular:

    • Ensures readiness histograms exist and are observed at 0.0s.
    • Ensures the canonical server request-duration histogram
      (`http_server_request_duration_seconds`) exists and is observed with
      labeled values for the `/metrics` route (GET, "/metrics", "200").

Layer:
    adapters/routers
"""

from __future__ import annotations

from collections.abc import Callable
from contextlib import suppress
from typing import TYPE_CHECKING

from fastapi import APIRouter, Response
from prometheus_client import CONTENT_TYPE_LATEST, generate_latest

from stacklion_api.infrastructure.logging.logger import get_json_logger
from stacklion_api.infrastructure.observability.metrics import (
    get_readyz_db_latency_seconds,
    get_readyz_redis_latency_seconds,
)

if TYPE_CHECKING:  # typing-only
    from prometheus_client import Histogram

logger = get_json_logger(__name__)
router = APIRouter()


def _get_server_histogram() -> Histogram | None:
    """Return the canonical server-side request histogram if available."""
    # Canonical location (RequestLatencyMiddleware)
    with suppress(Exception):
        from stacklion_api.infrastructure.middleware.request_metrics import (
            get_http_server_request_duration_seconds,
        )

        return get_http_server_request_duration_seconds()

    # Optional fallback: import for side effects (eager registration).
    with suppress(Exception):
        import stacklion_api.infrastructure.middleware.request_metrics as _req_metrics  # noqa: F401

        logger.debug("metrics_router: imported request_metrics for side effects")

    return None


def _ensure_observed_once(getter: Callable[[], Histogram], name: str) -> None:
    """Create (via getter) and ensure at least one observation (0.0 s)."""
    try:
        hist = getter()
        hist.observe(0.0)
    except Exception as exc:  # pragma: no cover (defensive)
        logger.debug(
            "metrics_router: failed warming histogram",
            extra={"extra": {"metric": name, "error": str(exc)}},
        )


@router.get("/metrics", include_in_schema=False)
async def metrics_probe() -> Response:
    """Expose Prometheus metrics; warm histograms so buckets exist on cold scrape."""
    _ensure_observed_once(get_readyz_db_latency_seconds, "readyz_db_latency_seconds")
    _ensure_observed_once(get_readyz_redis_latency_seconds, "readyz_redis_latency_seconds")

    server_hist = _get_server_histogram()
    if server_hist is not None:
        with suppress(Exception):
            server_hist.labels("GET", "/metrics", "200").observe(0.0)
            logger.debug("metrics_router: warmed http_server_request_duration_seconds with 0.0s")

    return Response(content=generate_latest(), media_type=CONTENT_TYPE_LATEST)
