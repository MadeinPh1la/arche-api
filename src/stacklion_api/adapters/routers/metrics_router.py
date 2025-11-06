# Copyright (c) Stacklion.
# SPDX-License-Identifier: MIT
"""Metrics router.

Exposes Prometheus metrics from the default registry at `/metrics`.
Registration is lazy: collectors are created when first used via getters.
"""

from __future__ import annotations

from fastapi import APIRouter, Response
from prometheus_client import CONTENT_TYPE_LATEST, REGISTRY, generate_latest

router = APIRouter()


@router.get("/metrics", include_in_schema=False, name="metrics_probe")
async def metrics_probe() -> Response:
    """Return Prometheus metrics text exposition from the default registry."""
    payload = generate_latest(REGISTRY)
    return Response(payload, media_type=CONTENT_TYPE_LATEST)
