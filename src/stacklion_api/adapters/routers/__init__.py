"""Routers Package Export (Adapters Layer).

Purpose:
    Provide stable, explicit exports for the application router aggregator (`api_router`)
    and the health router (`health_router`). The FastAPI application expects to import
    these names from this package during startup.

Design:
    - Avoids implicit imports by re-exporting concrete router instances.
    - Keeps application bootstrap (`main.py`) decoupled from router file layout.

Layer:
    adapters/routers
"""

from __future__ import annotations

from .api_router import router as api_router  # noqa: F401
from .health_router import router as health  # noqa: F401

__all__ = ["api_router", "health"]
