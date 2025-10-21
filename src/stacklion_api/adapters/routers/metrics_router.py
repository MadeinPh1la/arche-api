# Copyright (c) Stacklion.
# SPDX-License-Identifier: MIT
"""Metrics router.

Exposes Prometheus metrics from the default registry at `/metrics`. We import
the observability metrics module for its side effects so histogram definitions
are registered before this endpoint is scraped.
"""

from __future__ import annotations

from fastapi import APIRouter, Response
from prometheus_client import CONTENT_TYPE_LATEST, REGISTRY, generate_latest

# Ensure histograms/counters are registered on import.
# (Module-level import; no runtime cost beyond registration.)
from stacklion_api.infrastructure.observability import metrics as _obs_metrics  # noqa: F401

router = APIRouter()


@router.get("/metrics", include_in_schema=False, name="metrics_probe")
async def metrics_probe() -> Response:
    """Return Prometheus metrics text exposition from the default registry."""
    payload = generate_latest(REGISTRY)
    return Response(payload, media_type=CONTENT_TYPE_LATEST)
