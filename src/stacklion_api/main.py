# src/stacklion_api/main.py
# Copyright (c) Stacklion.
# SPDX-License-Identifier: MIT
"""
Application Entry (Adapters Bootstrap)

Synopsis:
    FastAPI bootstrap that wires middleware, the OpenAPI Contract Registry, and all
    routers. Provides an application factory (`create_app`) and a module-level
    eager app (`app`) for tooling and snapshot tests.

Design:
    • Bootstrap only (no business logic): routers + middleware + contract registry.
    • OpenAPI Contract Registry is attached first to stabilize snapshots.
    • Lifespan initializes DB/Redis/HTTP and tears them down safely.
    • CORS and security headers are applied consistently across environments.
    • Observability:
        - Root JSON logging configured at import time.
        - OpenTelemetry exporters initialized (soft dependency).
        - Tracing/metrics middleware installed for every request.
"""

from __future__ import annotations

import os
from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager

from fastapi import FastAPI, HTTPException
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.routing import APIRoute
from starlette.middleware.gzip import GZipMiddleware
from starlette.requests import Request
from starlette.responses import JSONResponse
from starlette.responses import Response as StarletteResponse

from stacklion_api.adapters.routers import mcp_router
from stacklion_api.adapters.routers.api_router import router as api_router
from stacklion_api.adapters.routers.edgar_router import router as edgar_router  # <-- EDGAR router
from stacklion_api.adapters.routers.metrics_router import router as metrics_router
from stacklion_api.adapters.routers.openapi_registry import (
    attach_openapi_contract_registry,
)
from stacklion_api.config.settings import Settings, get_settings
from stacklion_api.dependencies.core.bootstrap import bootstrap
from stacklion_api.infrastructure.http.errors import (
    handle_http_exception,
    handle_unhandled_exception,
    handle_validation_error,
)
from stacklion_api.infrastructure.http.middleware.trace import TraceIdMiddleware
from stacklion_api.infrastructure.logging.logger import (
    configure_root_logging,
    get_json_logger,
)
from stacklion_api.infrastructure.logging.tracing import configure_tracing
from stacklion_api.infrastructure.middleware.access_log import AccessLogMiddleware
from stacklion_api.infrastructure.middleware.idempotency import IdempotencyMiddleware
from stacklion_api.infrastructure.middleware.metrics import (
    PromMetricsMiddleware,  # optional extra counters
)
from stacklion_api.infrastructure.middleware.rate_limit import RateLimitMiddleware
from stacklion_api.infrastructure.middleware.request_id import RequestIdMiddleware
from stacklion_api.infrastructure.middleware.request_metrics import (
    RequestLatencyMiddleware,
)
from stacklion_api.infrastructure.middleware.security_headers import (
    SecurityHeadersMiddleware,
)
from stacklion_api.infrastructure.observability.metrics import (
    get_readyz_db_latency_seconds,
    get_readyz_redis_latency_seconds,
)
from stacklion_api.infrastructure.observability.otel import init_otel

# -----------------------------------------------------------------------------
# Logging
# -----------------------------------------------------------------------------
configure_root_logging()
logger = get_json_logger(__name__)


# -----------------------------------------------------------------------------
# Stable generator
# -----------------------------------------------------------------------------
def _stable_operation_id(route: APIRoute) -> str:
    """Deterministic operationId to stop OpenAPI snapshot churn.

    Format:
        "<methods>_<path>", e.g. "get__v1_protected_ping"
        where methods are sorted and path params braces are removed.

    Args:
        route: FastAPI APIRoute.

    Returns:
        str: Stable operationId for OpenAPI.
    """
    methods = ",".join(sorted(route.methods or []))
    path = route.path_format.replace("/", "_").replace("{", "").replace("}", "")
    return f"{methods.lower()}_{path.lower()}"


# -----------------------------------------------------------------------------
# Lifespan
# -----------------------------------------------------------------------------
@asynccontextmanager
async def runtime_lifespan(app: FastAPI) -> AsyncGenerator[None, None]:
    """Initialize and teardown shared infrastructure via the core bootstrap.

    This context manager delegates initialization of settings, logging, database
    engine, Redis client, HTTP clients, and tracing to the shared
    :func:`bootstrap` helper. It also exposes the resolved settings and shared
    HTTP client on ``app.state`` for downstream dependencies.

    Args:
        app: FastAPI application instance.

    Yields:
        None: Control back to FastAPI to serve requests.
    """
    async with bootstrap(app) as state:
        app.state.settings = state.settings
        app.state.http_client = state.http_client
        yield


# -----------------------------------------------------------------------------
# Middleware & CORS
# -----------------------------------------------------------------------------
def _attach_middlewares(app: FastAPI, settings: Settings) -> None:
    """Attach core middleware in the recommended order.

    Middleware ordering is intentionally strict to preserve logging and
    observability guarantees:

        1. RequestIdMiddleware / TraceIdMiddleware (correlation IDs)
        2. AccessLogMiddleware (structured access logs)
        3. RequestLatencyMiddleware + PromMetricsMiddleware (metrics)
        4. SecurityHeadersMiddleware (defensive headers)
        5. IdempotencyMiddleware (dedupe write operations)
        6. RateLimitMiddleware (optional HTTP rate limiting)
        7. GZipMiddleware (response compression)

    Args:
        app: FastAPI application.
        settings: Runtime settings for environment-aware toggles.
    """
    # Correlation ID chain: RequestIdMiddleware complements TraceIdMiddleware.
    app.add_middleware(RequestIdMiddleware)

    # Access log should see request_id/trace_id on request.state and contextvars.
    app.add_middleware(AccessLogMiddleware)

    # Canonical server latency histogram (required by tests).
    app.add_middleware(RequestLatencyMiddleware)

    # Optional additional Prometheus counters/histograms.
    app.add_middleware(PromMetricsMiddleware)

    app.add_middleware(SecurityHeadersMiddleware)

    # HTTP idempotency for write operations (POST/PUT/PATCH/DELETE).
    if settings.idempotency_enabled:
        app.add_middleware(
            IdempotencyMiddleware,
            ttl_seconds=settings.idempotency_ttl_seconds,
        )
        logger.info(
            "idempotency_enabled",
            extra={
                "ttl_seconds": settings.idempotency_ttl_seconds,
            },
        )

    # Rate limit (settings + env legacy overrides).
    env_enabled = os.getenv("RATE_LIMIT_ENABLED", "").strip().lower() == "true"
    enabled = env_enabled or settings.rate_limit_enabled
    if enabled:
        window = max(
            1, int(os.getenv("RATE_LIMIT_WINDOW_SECONDS") or settings.rate_limit_window_seconds)
        )
        burst = max(1, int(os.getenv("RATE_LIMIT_BURST") or settings.rate_limit_burst))
        rate_per_sec = max(1.0, float(burst) / float(window))
        app.add_middleware(RateLimitMiddleware, rate_per_sec=rate_per_sec, burst=burst)
        logger.info(
            "rate_limit_enabled",
            extra={"window_s": window, "burst": burst, "rate_per_sec": rate_per_sec},
        )

    # Response compression.
    app.add_middleware(GZipMiddleware, minimum_size=1024)


def _attach_cors(app: FastAPI, settings: Settings) -> None:
    """Attach CORS middleware based on settings.

    Args:
        app: FastAPI application.
        settings: Runtime settings containing CORS config.
    """
    allow_origins = settings.cors_allow_origins or ["*"]
    allow_credentials = True
    allow_methods = ["*"]
    allow_headers = ["*"]

    app.add_middleware(
        CORSMiddleware,
        allow_origins=allow_origins,
        allow_credentials=allow_credentials,
        allow_methods=allow_methods,
        allow_headers=allow_headers,
    )


def _patch_exception_handlers(app: FastAPI) -> None:
    """Patch default exception handlers with structured equivalents.

    Args:
        app: FastAPI application.
    """

    async def _http_error_handler(request: Request, exc: Exception) -> StarletteResponse:
        if not isinstance(exc, HTTPException):
            # Let FastAPI/Starlette bubble unexpected exception types to their
            # own handlers (including the generic Exception handler below).
            raise exc
        return await handle_http_exception(request, exc)

    async def _validation_error_handler(request: Request, exc: Exception) -> StarletteResponse:
        if not isinstance(exc, RequestValidationError):
            raise exc
        return await handle_validation_error(request, exc)

    async def _unhandled_error_handler(request: Request, exc: Exception) -> StarletteResponse:
        return await handle_unhandled_exception(request, exc)

    app.add_exception_handler(HTTPException, _http_error_handler)
    app.add_exception_handler(RequestValidationError, _validation_error_handler)
    app.add_exception_handler(Exception, _unhandled_error_handler)


# -----------------------------------------------------------------------------
# App factory
# -----------------------------------------------------------------------------
def create_app() -> FastAPI:
    """Create and configure the FastAPI application.

    Returns:
        FastAPI: Fully configured application instance.
    """
    settings: Settings = get_settings()

    service_name = "stacklion-api"
    service_version = os.getenv("SERVICE_VERSION") or settings.service_version or "0.0.0"

    app = FastAPI(
        title="Stacklion API",
        version=service_version,
        description="Secure, governed financial data API.",
        lifespan=runtime_lifespan,
        generate_unique_id_function=_stable_operation_id,
    )

    # Initialize OpenTelemetry exporters/providers (soft dependency).
    try:
        init_otel(service_name=service_name, service_version=service_version)
    except Exception as exc:  # pragma: no cover - observability must not break startup
        logger.debug(
            "otel.init_failed",
            extra={"extra": {"error": str(exc)}},
        )

    # Attach OTEL ASGI/FastAPI/HTTPX/SQLAlchemy instrumentation (soft dependency).
    try:
        configure_tracing(app)
    except Exception as exc:  # pragma: no cover - observability must not break startup
        logger.debug(
            "otel.configure_tracing_failed",
            extra={"extra": {"error": str(exc)}},
        )

    # Attach trace-id middleware early so logs can correlate requests.
    app.add_middleware(TraceIdMiddleware)

    _patch_exception_handlers(app)

    # --- Warm readiness histograms so *_bucket exists on the very first scrape ---
    try:
        get_readyz_db_latency_seconds().observe(0.0)
        get_readyz_redis_latency_seconds().observe(0.0)
    except Exception as exc:  # pragma: no cover
        logger.debug(
            "startup: readiness histogram warm-up skipped",
            extra={"extra": {"error": str(exc)}},
        )

    # Contract Registry FIRST to stabilize OpenAPI snapshots.
    attach_openapi_contract_registry(app)

    _attach_middlewares(app, settings)
    _attach_cors(app, settings)

    # Mount all API routers via the aggregator (health, historical, protected, etc.)
    app.include_router(api_router)

    # EDGAR router (v1/edgar/* endpoints)
    app.include_router(edgar_router)

    # MCP router
    app.include_router(mcp_router.router)

    # Metrics router (typically exposes /metrics).
    app.include_router(metrics_router)

    # Simple /healthz endpoint used by rate-limit header tests.
    @app.get("/healthz")
    async def healthz() -> JSONResponse:
        """Lightweight health endpoint behind rate limiting.

        Returns:
            JSONResponse: Simple status payload used to exercise RateLimitMiddleware.
        """
        return JSONResponse({"status": "ok"})

    logger.info(
        "service_startup",
        extra={
            "service": service_name,
            "env": settings.environment.value,
            "version": service_version,
            "status": "starting",
        },
    )
    return app


# Eager app for tools and snapshot tests.
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
