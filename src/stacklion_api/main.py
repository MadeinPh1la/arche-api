# Copyright (c) Stacklion.
# SPDX-License-Identifier: MIT
"""
Application Entry (Adapters Bootstrap)

Synopsis:
    FastAPI bootstrap that wires middleware, the OpenAPI Contract Registry, and all
    routers. Provides an application factory (`create_app`) and a module-level
    eager app (`app`) for tooling and snapshot tests.

Design:
    * Bootstrap only; no business logic.
    * Contract Registry attached first to guarantee canonical envelopes.
    * Health-first fallback ensures /openapi.json is always live in CI.
    * Settings are read via `get_settings()` and used for:
        - CORS allow-list
        - Rate limiting selection (memory/redis)
        - Environment-aware behavior

Run (factory):
    uvicorn stacklion_api.main:create_app --factory --reload

Attributes:
    app (FastAPI): Eagerly-created application. Exposed to support tools/tests
        that import ``stacklion_api.main:app`` (e.g., OpenAPI snapshot tests).
"""

from __future__ import annotations

import logging
import os
import time
from collections.abc import Callable
from typing import Any, cast

from fastapi import APIRouter, FastAPI, HTTPException, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from starlette import status
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.middleware.cors import CORSMiddleware
from starlette.middleware.gzip import GZipMiddleware
from starlette.routing import BaseRoute

# Adapters / middleware
from stacklion_api.adapters.routers.metrics_router import router as metrics_router
from stacklion_api.adapters.routers.openapi_registry import attach_openapi_contract_registry
from stacklion_api.config.settings import get_settings
from stacklion_api.infrastructure.logging import logger as _logmod
from stacklion_api.infrastructure.middleware.access_log import AccessLogMiddleware
from stacklion_api.infrastructure.middleware.metrics import PromMetricsMiddleware
from stacklion_api.infrastructure.middleware.rate_limit import RateLimitMiddleware
from stacklion_api.infrastructure.middleware.request_id import RequestIdMiddleware
from stacklion_api.infrastructure.middleware.security_headers import SecurityHeadersMiddleware

# Optional Redis-backed rate limit middleware (may not be installed in all envs)
try:
    from stacklion_api.infrastructure.middleware.rate_limit_redis import (
        RateLimitMiddlewareRedis as _RedisMW,
    )

    RateLimitMiddlewareRedis: type[BaseHTTPMiddleware] | None = _RedisMW
except Exception:  # pragma: no cover - optional import
    RateLimitMiddlewareRedis = None

# -----------------------------------------------------------------------------
# Logging bootstrap
# -----------------------------------------------------------------------------
configure_root_logging: Callable[[], None] = getattr(
    _logmod, "configure_root_logging", lambda: None
)
get_json_logger: Callable[[str], logging.Logger] = getattr(
    _logmod, "get_json_logger", lambda name: logging.getLogger(name)
)
configure_root_logging()
logger = get_json_logger(__name__)


# -----------------------------------------------------------------------------
# Internal helpers (kept small to satisfy lints and readability)
# -----------------------------------------------------------------------------
def _init_middlewares(app: FastAPI, settings: Any) -> None:
    """Attach core middleware in the correct order."""
    # RequestId -> AccessLog -> Metrics -> SecurityHeaders -> RateLimit -> GZip
    app.add_middleware(RequestIdMiddleware)
    app.add_middleware(AccessLogMiddleware)
    app.add_middleware(PromMetricsMiddleware)
    app.add_middleware(SecurityHeadersMiddleware)

    if settings.rate_limit_enabled:
        if settings.rate_limit_backend == "redis" and RateLimitMiddlewareRedis is not None:
            app.add_middleware(
                cast(Any, RateLimitMiddlewareRedis),
                redis_url=settings.redis_url,
                burst=settings.rate_limit_burst,
                window_s=settings.rate_limit_window_seconds,
            )
            logger.info("rate_limit_enabled")
        else:
            rate_per_sec = max(
                1.0,
                float(settings.rate_limit_burst)
                / float(max(1, settings.rate_limit_window_seconds)),
            )
            app.add_middleware(
                RateLimitMiddleware,
                rate_per_sec=rate_per_sec,
                burst=settings.rate_limit_burst,
            )
            logger.info("rate_limit_enabled")

    app.add_middleware(GZipMiddleware, minimum_size=1024)


def _add_cors(app: FastAPI, settings: Any) -> None:
    """Add CORS with exposure headers when configured."""
    origins = settings.cors_allow_origins
    if not origins:
        return

    # If dev/test wants "*", use regex to support allow_credentials=True
    allow_origin_regex = None
    allow_origins = origins
    if origins == ["*"]:
        allow_origins = []  # Starlette ignores "*" with credentials
        allow_origin_regex = ".*"  # allow any origin in dev/test

    app.add_middleware(
        CORSMiddleware,
        allow_origins=allow_origins,
        allow_origin_regex=allow_origin_regex,
        allow_credentials=True,
        allow_methods=["GET", "POST", "PUT", "PATCH", "DELETE", "OPTIONS"],
        allow_headers=["*"],
        expose_headers=[
            "ETag",
            "X-Request-ID",
            "X-RateLimit-Limit",
            "X-RateLimit-Remaining",
            "X-RateLimit-Reset",
            "Retry-After",
        ],
    )


def _add_error_handlers(app: FastAPI) -> None:
    """Register canonical error envelopes."""

    @app.exception_handler(RequestValidationError)
    async def _validation_exception_handler(
        request: Request, exc: RequestValidationError
    ) -> JSONResponse:
        """Return a canonical adapters-level validation error envelope."""
        trace_id = getattr(getattr(request, "state", object()), "request_id", None)
        payload: dict[str, Any] = {
            "error": {
                "code": "VALIDATION_ERROR",
                "http_status": status.HTTP_422_UNPROCESSABLE_ENTITY,
                "message": "Request validation failed",
                "details": exc.errors(),
                "trace_id": trace_id,
            }
        }
        headers = {"X-Request-ID": str(trace_id)} if trace_id else {}
        return JSONResponse(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            content=payload,
            headers=headers,
        )


def _add_healthz(app: FastAPI, settings: Any) -> None:
    """Add a schema-hidden /healthz with a simple burst/window limiter using raw env."""
    _h_state = {"start": 0.0, "count": 0}

    async def _healthz() -> JSONResponse:
        enabled = (os.getenv("RATE_LIMIT_ENABLED", "") or "").lower() == "true"
        burst = int(os.getenv("RATE_LIMIT_BURST", settings.rate_limit_burst or 5))
        window = int(
            os.getenv("RATE_LIMIT_WINDOW_SECONDS", settings.rate_limit_window_seconds or 1)
        )

        now = time.monotonic()
        if now - _h_state["start"] >= float(window):
            _h_state["start"] = now
            _h_state["count"] = 0

        _h_state["count"] += 1
        if enabled and _h_state["count"] > burst:
            headers = {
                "X-RateLimit-Limit": str(burst),
                "X-RateLimit-Remaining": str(max(0, burst - _h_state["count"])),
                "X-RateLimit-Reset": str(window),
                "Retry-After": str(window),
            }
            return JSONResponse(
                status_code=429, content={"detail": "Too Many Requests"}, headers=headers
            )

        return JSONResponse(status_code=200, content={"status": "ok"})

    app.add_api_route(
        "/healthz",
        _healthz,
        methods=["GET"],
        include_in_schema=False,
        name="healthz_probe",
    )


def _mount_metrics(app: FastAPI) -> None:
    """Expose /metrics for Prometheus (hidden from OpenAPI at the router level)."""
    app.include_router(metrics_router)


def _mount_project_api(app: FastAPI, service_name: str) -> None:
    """Attempt to mount the project API router; log if unavailable."""
    try:
        from .adapters.routers import api_router

        app.include_router(api_router)
    except Exception as exc:  # pragma: no cover
        logger.exception("router_import_failed", extra={"error": str(exc), "service": service_name})


def _route_exists(app: FastAPI, path: str, method: str) -> bool:
    """Return True if a route with `path` and HTTP `method` is mounted."""
    m = method.upper()
    for r in app.router.routes:
        path_attr = getattr(r, "path", None)
        methods = getattr(r, "methods", None)
        if (
            isinstance(r, BaseRoute)
            and isinstance(path_attr, str)
            and methods
            and m in methods
            and path_attr == path
        ):
            return True
    return False


def _ensure_protected_ping(app: FastAPI) -> None:
    """Mount a schema-hidden /v1/protected/ping if the project doesn't provide one."""
    if _route_exists(app, "/v1/protected/ping", "GET"):
        return

    protected = APIRouter(prefix="/v1/protected", include_in_schema=False)

    @protected.get("/ping", name="protected_ping")
    async def _protected_ping(request: Request) -> dict[str, str]:
        """Simple protected probe: 401 without valid HS256 token when AUTH is enabled."""
        auth_enabled = (os.getenv("AUTH_ENABLED", "") or "").lower() == "true"
        if not auth_enabled:
            return {"status": "ok"}

        auth = request.headers.get("authorization") or request.headers.get("Authorization")
        if not auth or not auth.lower().startswith("bearer "):
            raise HTTPException(status_code=401, detail="Missing bearer token")
        token = auth.split(" ", 1)[1].strip()

        # Guard secret so decode never sees Optional[str]
        secret = os.getenv("AUTH_HS256_SECRET") or ""
        if not secret:
            raise HTTPException(status_code=401, detail="Invalid token")

        import jwt as pyjwt  # PyJWT

        try:
            pyjwt.decode(token, secret, algorithms=["HS256"])
        except Exception as _err:
            # Hide decode internals; ensure exception provenance is clear for linters.
            raise HTTPException(status_code=401, detail="Invalid token") from None

        return {"status": "ok"}

    app.include_router(protected)


# -----------------------------------------------------------------------------
# Application factory
# -----------------------------------------------------------------------------
def create_app() -> FastAPI:
    """Create and configure the FastAPI application.

    Returns:
        FastAPI: Fully configured application.
    """
    settings = get_settings()
    env = settings.environment.value
    service_name = "stacklion-api"
    service_version = os.getenv("SERVICE_VERSION") or settings.service_version or "0.1.0"

    app = FastAPI(
        title="Stacklion API",
        version=service_version,
        description="A secure, governed API platform that consolidates regulatory filings, market data, and portfolio intelligence into a single, auditable financial data backbone.",
    )

    attach_openapi_contract_registry(app)
    _init_middlewares(app, settings)
    _add_cors(app, settings)
    _add_error_handlers(app)
    _add_healthz(app, settings)
    _mount_metrics(app)
    _mount_project_api(app, service_name)
    _ensure_protected_ping(app)

    logger.info(
        "service_startup",
        extra={
            "service": service_name,
            "env": env,
            "version": service_version,
            "status": "starting",
        },
    )
    return app


# Eager app for tools/tests that import `stacklion_api.main:app`
app: FastAPI = create_app()

if __name__ == "__main__":  # pragma: no cover
    import uvicorn

    uvicorn.run(
        "stacklion_api.main:create_app",
        factory=True,
        host="127.0.0.1",
        port=int(os.getenv("PORT", "8080")),
        reload=True,
    )
    logger.info("service_shutdown", extra={"service": "stacklion-api", "status": "stopped"})
