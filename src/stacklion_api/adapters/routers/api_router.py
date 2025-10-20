"""
API Router Aggregator (Adapters Layer)

Purpose:
    Compose and expose the top-level `api_router` that includes all feature routers.
    This is the canonical place to register resource-specific routers into the app.

How it works:
    - Imports concrete routers (e.g., health, companies, analysis).
    - Applies resource-specific prefixes and tags where appropriate.
    - Exports a single `router` mounted by `main.py`.

Layer:
    adapters/routers
"""

from __future__ import annotations

from fastapi import APIRouter

# Import concrete feature routers here.
# Health is always included.
from .health_router import router as health_router

# Example: add more feature routers as they come online:
# from .companies_router import router as companies_router
# from .analysis_router import router as analysis_router

router = APIRouter()

# Health endpoints (liveness/readiness). Kept under a dedicated prefix.
router.include_router(health_router, prefix="/health", tags=["Health"])

# Example: add resources as they are implemented.
# router.include_router(companies_router, prefix="/companies", tags=["Companies"])
# router.include_router(analysis_router, prefix="/analysis", tags=["Analysis"])
