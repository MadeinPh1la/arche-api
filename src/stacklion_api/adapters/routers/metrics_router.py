# Copyright (c) Stacklion.
# SPDX-License-Identifier: MIT
"""
Metrics Router.

Summary:
    Exposes a `/metrics` endpoint for metrics scraping. By default this returns
    an empty Prometheus exposition so imports and wiring remain stable. Replace
    the body with your exporter (e.g., `prometheus_client`) when ready.

Notes:
    * The route is hidden from OpenAPI via `include_in_schema=False`.
"""

from __future__ import annotations

from fastapi import APIRouter, Response

__all__ = ["router"]

router = APIRouter()


@router.get("/metrics", include_in_schema=False)
async def metrics_probe() -> Response:
    """Return a metrics payload suitable for Prometheus scraping.

    Returns:
        Response: A text/plain payload in Prometheus exposition format.
    """
    # TODO: replace with real exposition, e.g.:
    # from prometheus_client import generate_latest, CONTENT_TYPE_LATEST
    # return Response(generate_latest(), media_type=CONTENT_TYPE_LATEST)
    return Response(content="", media_type="text/plain; version=0.0.4")
