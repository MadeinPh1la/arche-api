# src/stacklion_api/adapters/routers/api_router.py
"""
API Router Aggregator (Adapters Layer)

Purpose:
    Compose and expose the top-level `api_router` that includes all feature routers.
    This is the canonical place to register resource-specific routers into the app.

How it works:
    - Imports concrete routers (e.g., health, quotes, protected).
    - Applies resource-specific prefixes and tags where appropriate.
    - Exports a single `router` mounted by `main.py`.

Layer:
    adapters/routers
"""

from __future__ import annotations

from fastapi import APIRouter

from stacklion_api.adapters.routers.health_router import router as health_router
from stacklion_api.adapters.routers.historical_quotes_router import (
    router as historical_quotes_router,
)
from stacklion_api.adapters.routers.protected_router import get_router as get_protected_router

router = APIRouter()

# Health endpoints (liveness/readiness) under /health.
router.include_router(health_router, prefix="/health", tags=["Health"])

# Historical quotes (v2) – BaseRouter already includes /v2/quotes prefix.
router.include_router(historical_quotes_router, tags=["Market Data"])

# Protected ping /v1/protected/ping (feature-flagged auth).
router.include_router(get_protected_router(), tags=["Auth"])
