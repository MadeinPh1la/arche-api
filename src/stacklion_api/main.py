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
"""

from __future__ import annotations

import os
from collections.abc import AsyncGenerator, Awaitable, Callable
from contextlib import asynccontextmanager
from typing import cast

import httpx
from fastapi import FastAPI, HTTPException
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from starlette.middleware.gzip import GZipMiddleware
from starlette.requests import Request
from starlette.responses import Response as StarletteResponse

from stacklion_api.adapters.routers.health_router import (
    get_health_probe as _get_probe_dep,
)
from stacklion_api.adapters.routers.health_router import router as health_router
from stacklion_api.adapters.routers.historical_quotes_router import (
    router as historical_quotes_router,
)
from stacklion_api.adapters.routers.metrics_router import router as metrics_router
from stacklion_api.adapters.routers.openapi_registry import (
    attach_openapi_contract_registry,
)
from stacklion_api.adapters.routers.protected_router import get_router as get_protected_router
from stacklion_api.config.settings import Settings, get_settings
from stacklion_api.infrastructure.caching.redis_client import close_redis, init_redis
from stacklion_api.infrastructure.database.session import (
    dispose_engine,
    init_engine_and_sessionmaker,
)
from stacklion_api.infrastructure.http.errors import (
    handle_http_exception,
    handle_unhandled_exception,
    handle_validation_error,
)
from stacklion_api.infrastructure.http.middleware.trace import TraceIdMiddleware
from stacklion_api.infrastructure.logging.logger import configure_root_logging, get_json_logger
from stacklion_api.infrastructure.middleware.access_log import AccessLogMiddleware
from stacklion_api.infrastructure.middleware.metrics import (
    PromMetricsMiddleware,  # optional extra counters
)
from stacklion_api.infrastructure.middleware.rate_limit import RateLimitMiddleware
from stacklion_api.infrastructure.middleware.request_id import RequestIdMiddleware
from stacklion_api.infrastructure.middleware.request_metrics import RequestLatencyMiddleware
from stacklion_api.infrastructure.middleware.security_headers import SecurityHeadersMiddleware
from stacklion_api.infrastructure.observability.metrics import (
    get_readyz_db_latency_seconds,
    get_readyz_redis_latency_seconds,
)

# OpenTelemetry init (no-op if not enabled via env)
try:  # pragma: no cover
    from stacklion_api.infrastructure.observability.otel import init_otel
except Exception:  # pragma: no cover

    def init_otel(*_args: object, **_kwargs: object) -> None:
        """Graceful no-op when OTEL is not available."""
        return


# -----------------------------------------------------------------------------
# Logging
# -----------------------------------------------------------------------------
configure_root_logging()
logger = get_json_logger(__name__)


# -----------------------------------------------------------------------------
# Lifespan
# -----------------------------------------------------------------------------
@asynccontextmanager
async def runtime_lifespan(app: FastAPI) -> AsyncGenerator[None, None]:
    """Initialize and teardown shared infrastructure (DB/Redis/HTTP clients).

    This context manager is invoked once when the application starts and ends,
    ensuring connection pools are reused and disposed deterministically.

    Yields:
        None: Control back to FastAPI to serve requests.
    """
    settings: Settings = get_settings()
    init_engine_and_sessionmaker(settings)
    init_redis(settings)

    try:
        yield
    finally:
        client = getattr(app.state, "http_client", None)
        if isinstance(client, httpx.AsyncClient):
            try:
                await client.aclose()
            except Exception as exc:  # pragma: no cover
                logger.warning("http_client_close_failed", extra={"error": str(exc)})

        try:
            await close_redis()
        except Exception as exc:  # pragma: no cover
            logger.warning("redis_close_failed", extra={"error": str(exc)})

        try:
            await dispose_engine()
        except Exception as exc:  # pragma: no cover
            logger.warning("db_dispose_failed", extra={"error": str(exc)})


# -----------------------------------------------------------------------------
# Middleware & CORS
# -----------------------------------------------------------------------------
def _attach_middlewares(app: FastAPI, settings: Settings) -> None:
    """Attach core middleware in the recommended order.

    Args:
        app: FastAPI application.
        settings: Runtime settings for environment-aware toggles.
    """
    app.add_middleware(RequestIdMiddleware)
    app.add_middleware(AccessLogMiddleware)

    # Canonical server latency histogram (required by tests).
    app.add_middleware(RequestLatencyMiddleware)

    # Optional additional Prometheus counters/histograms.
    app.add_middleware(PromMetricsMiddleware)

    app.add_middleware(SecurityHeadersMiddleware)

    # Rate limit (env or settings).
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

    # Response compression
    app.add_middleware(GZipMiddleware, minimum_size=1024)


def _attach_cors(app: FastAPI, settings: Settings) -> None:
    """Attach CORS with explicit exposed headers if configured.

    Args:
        app: FastAPI application.
        settings: Runtime settings including CORS allow list.
    """
    allowed = settings.cors_allow_origins
    if allowed:
        allow_origins = [] if allowed == ["*"] else allowed
        allow_origin_regex = ".*" if allowed == ["*"] else None
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


# -----------------------------------------------------------------------------
# App Factory
# -----------------------------------------------------------------------------

Handler = Callable[[Request, Exception], StarletteResponse | Awaitable[StarletteResponse]]


def create_app() -> FastAPI:
    """Create and configure the FastAPI application.

    Returns:
        FastAPI: Fully configured application instance.
    """
    settings: Settings = get_settings()

    service_name = "stacklion-api"
    service_version = os.getenv("SERVICE_VERSION") or settings.service_version or "0.0.0"

    init_otel(service_name=service_name, service_version=service_version)

    app = FastAPI(
        title="Stacklion API",
        version=service_version,
        description="Secure, governed financial data API.",
        lifespan=runtime_lifespan,
    )

    # Ensure shared HTTP client exists before dependency wiring
    if not hasattr(app.state, "http_client"):
        app.state.http_client = httpx.AsyncClient()

    # Contract Registry FIRST to stabilize OpenAPI snapshots.
    attach_openapi_contract_registry(app)

    _attach_middlewares(app, settings)
    _attach_cors(app, settings)

    app.add_middleware(TraceIdMiddleware)

    # mypy: add_exception_handler expects a generic Exception handler signature.
    # Our funcs are more specific; cast them to the accepted type.
    app.add_exception_handler(RequestValidationError, cast(Handler, handle_validation_error))
    app.add_exception_handler(HTTPException, cast(Handler, handle_http_exception))
    app.add_exception_handler(Exception, cast(Handler, handle_unhandled_exception))

    # /metrics
    app.include_router(metrics_router)

    # Protected sample surface (auth feature-flag)
    app.include_router(get_protected_router())

    # Health endpoints (/health/z, /health/ready)
    app.include_router(health_router, prefix="/health")

    # Emit readiness histograms even if no real probe is configured.
    class _MetricsOnlyProbe:
        async def db(self) -> tuple[bool, str | None]:
            get_readyz_db_latency_seconds().observe(0.001)
            return False, "no db probe configured"

        async def redis(self) -> tuple[bool, str | None]:
            get_readyz_redis_latency_seconds().observe(0.001)
            return False, "no redis probe configured"

    app.dependency_overrides[_get_probe_dep] = lambda: _MetricsOnlyProbe()

    # Simple liveness used by rate-limit tests
    @app.get("/healthz")
    async def _healthz() -> dict[str, str]:
        """Simple process liveness endpoint."""
        return {"status": "ok"}

    # ------------------------------------------------------------------
    # Routers
    # ------------------------------------------------------------------
    # A6 historical quotes router: the actual gateway/UC is provided via DI
    # in `dependencies/market_data.py` (which handles test vs. prod wiring).
    app.include_router(historical_quotes_router)

    logger.info(
        "service_startup",
        extra={
            "service": service_name,
            "env": str(
                getattr(settings, "environment", None) or os.getenv("ENVIRONMENT", "unknown")
            ),
            "version": service_version,
            "status": "starting",
        },
    )
    return app


# Eager app for tools and snapshot tests
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
