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
    app: Eagerly-created application. Exposed to support tools/tests that import
        ``stacklion_api.main:app`` (e.g., OpenAPI snapshot tests).
"""

from __future__ import annotations

import logging
import os
import time
from collections.abc import AsyncGenerator, Callable
from contextlib import asynccontextmanager
from typing import Annotated, Any, cast

import redis.asyncio as aioredis
from fastapi import APIRouter, Depends, FastAPI, HTTPException, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from sqlalchemy.ext.asyncio import AsyncSession
from starlette import status
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.middleware.cors import CORSMiddleware
from starlette.middleware.gzip import GZipMiddleware
from starlette.routing import BaseRoute

# Adapters / middleware
from stacklion_api.adapters.dependencies.health_probe import PostgresRedisProbe
from stacklion_api.adapters.routers.health_router import get_health_probe
from stacklion_api.adapters.routers.metrics_router import router as metrics_router
from stacklion_api.adapters.routers.openapi_registry import attach_openapi_contract_registry
from stacklion_api.config.settings import Settings, get_settings
from stacklion_api.infrastructure.caching.redis_client import (
    close_redis,
    init_redis,
    redis_dependency,
)
from stacklion_api.infrastructure.database.session import (
    dispose_engine,
    get_db_session,
    init_engine_and_sessionmaker,
)
from stacklion_api.infrastructure.logging import logger as _logmod
from stacklion_api.infrastructure.middleware.access_log import AccessLogMiddleware
from stacklion_api.infrastructure.middleware.metrics import PromMetricsMiddleware
from stacklion_api.infrastructure.middleware.rate_limit import RateLimitMiddleware
from stacklion_api.infrastructure.middleware.request_id import RequestIdMiddleware
from stacklion_api.infrastructure.middleware.request_metrics import RequestLatencyMiddleware
from stacklion_api.infrastructure.middleware.security_headers import SecurityHeadersMiddleware
from stacklion_api.infrastructure.observability import metrics as _obs_metrics  # noqa: F401
from stacklion_api.infrastructure.observability.otel import init_otel

# Optional quotes router (A5) — safe to omit on branches without quotes
quotes_router: APIRouter | None = None
_QUOTES_ROUTER_AVAILABLE: bool = False
try:
    from stacklion_api.adapters.routers.quotes_router import router as _qr
    quotes_router = _qr
    _QUOTES_ROUTER_AVAILABLE = True
except Exception as exc:  # pragma: no cover
    import logging as _logging
    _logging.getLogger(__name__).warning("quotes_router_unavailable", extra={"error": str(exc)})

# Optional Redis-backed rate limit middleware (may not be installed in all envs)
try:
    from stacklion_api.infrastructure.middleware.rate_limit_redis import (
        RateLimitMiddlewareRedis as _RedisMW,
    )

    RateLimitMiddlewareRedis: type[BaseHTTPMiddleware] | None = _RedisMW
except Exception:  # pragma: no cover - optional import not always present
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
# Infrastructure DI providers (Postgres/Redis)
# -----------------------------------------------------------------------------
async def get_db_session_dep() -> AsyncGenerator[AsyncSession, None]:
    """Yield a typed async DB session (FastAPI dependency).

    Yields:
        AsyncSession: A SQLAlchemy async session.
    """
    async with get_db_session() as session:
        yield session


async def get_redis_client_dep() -> AsyncGenerator[aioredis.Redis[Any], None]:
    """Yield the shared Redis client (FastAPI dependency).

    Yields:
        redis.asyncio.Redis[Any]: The shared Redis client.
    """
    async with redis_dependency() as client:
        yield client


def _init_middlewares(app: FastAPI, settings: Any) -> None:
    """Attach core middleware in the correct order.

    Args:
        app: FastAPI application instance.
        settings: Application settings object (may not always expose every attr during rebase).
    """
    # RequestId -> AccessLog -> RequestLatency (OTEL) -> PromMetrics -> SecurityHeaders -> RateLimit -> GZip
    app.add_middleware(RequestIdMiddleware)
    app.add_middleware(AccessLogMiddleware)

    # Prefer Settings; fall back to env only if the attr isn't available
    otel_enabled = getattr(settings, "otel_enabled", None)
    if otel_enabled is None:
        otel_enabled = (os.getenv("OTEL_ENABLED", "") or "").lower() == "true"

    if otel_enabled:
        app.add_middleware(RequestLatencyMiddleware)

    # Prometheus request metrics (after OTEL so spans wrap the whole request)
    app.add_middleware(PromMetricsMiddleware)

    # Security headers
    app.add_middleware(SecurityHeadersMiddleware)

    # Rate limit
    if getattr(settings, "rate_limit_enabled", False):
        if (
            getattr(settings, "rate_limit_backend", "") == "redis"
            and RateLimitMiddlewareRedis is not None
        ):
            app.add_middleware(
                cast(Any, RateLimitMiddlewareRedis),
                redis_url=settings.redis_url,
                burst=settings.rate_limit_burst,
                window_s=settings.rate_limit_window_seconds,
            )
            logger.info("rate_limit_enabled", extra={"backend": "redis"})
        else:
            # Guard against zero/neg window just in case
            window = max(1, int(getattr(settings, "rate_limit_window_seconds", 1)))
            rate_per_sec = max(1.0, float(settings.rate_limit_burst) / float(window))
            app.add_middleware(
                RateLimitMiddleware,
                rate_per_sec=rate_per_sec,
                burst=settings.rate_limit_burst,
            )
            logger.info("rate_limit_enabled", extra={"backend": "memory"})

    # Compression last
    app.add_middleware(GZipMiddleware, minimum_size=1024)


def _add_cors(app: FastAPI, settings: Any) -> None:
    """Add CORS with exposure headers when configured.

    Args:
        app: FastAPI application instance.
        settings: Application settings object.
    """
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
    """Register canonical error envelopes.

    Args:
        app: FastAPI application instance.
    """

    @app.exception_handler(RequestValidationError)
    async def _validation_exception_handler(  # noqa: D401 - nested handler doc is above
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
    """Add a schema-hidden /healthz with a simple burst/window limiter using env.

    Args:
        app: FastAPI application instance.
        settings: Application settings object.
    """
    _h_state: dict[str, float | int] = {"start": 0.0, "count": 0}

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
        if enabled and int(_h_state["count"]) > burst:
            headers = {
                "X-RateLimit-Limit": str(burst),
                "X-RateLimit-Remaining": str(max(0, burst - int(_h_state["count"]))),
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
    """Expose /metrics for Prometheus (hidden from OpenAPI at the router level).

    Args:
        app: FastAPI application instance.
    """
    app.include_router(metrics_router)


def _mount_project_api(app: FastAPI, service_name: str) -> None:
    """Attempt to mount the project API router; log if unavailable.

    Args:
        app: FastAPI application instance.
        service_name: Logical service name for logs.
    """
    try:
        from .adapters.routers import api_router

        app.include_router(api_router)
    except Exception as exc:  # pragma: no cover
        logger.exception("router_import_failed", extra={"error": str(exc), "service": service_name})


def _route_exists(app: FastAPI, path: str, method: str) -> bool:
    """Return True if a route with `path` and HTTP `method` is mounted.

    Args:
        app: FastAPI application instance.
        path: The route path to check.
        method: HTTP method to check.

    Returns:
        True if the method/path exists on the router; otherwise False.
    """
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
    """Mount /v1/protected/ping if the project doesn't provide one.

    Args:
        app: FastAPI application instance.
    """
    if _route_exists(app, "/v1/protected/ping", "GET"):
        return

    protected = APIRouter(prefix="/v1/protected", include_in_schema=False)

    @protected.get("/ping", name="protected_ping")
    async def _protected_ping(request: Request) -> dict[str, str]:
        """Return 401 when AUTH is enabled and a valid token is not provided.

        Args:
            request: Incoming request.

        Returns:
            A minimal JSON status payload.

        Raises:
            HTTPException: When authentication is required and invalid.
        """
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
        except Exception as _err:  # noqa: F841
            # Hide decode internals; ensure exception provenance is clear for linters.
            raise HTTPException(status_code=401, detail="Invalid token") from None

        return {"status": "ok"}

    app.include_router(protected)


# -----------------------------------------------------------------------------
# Application factory (+ lifespan for real infra clients)
# -----------------------------------------------------------------------------
def create_app() -> FastAPI:
    """Create and configure the FastAPI application.

    Returns:
        FastAPI: Fully configured application.
    """
    settings: Settings = get_settings()
    env = settings.environment.value
    service_name = "stacklion-api"
    service_version = os.getenv("SERVICE_VERSION") or settings.service_version or "0.1.0"

    # Initialize OTEL/exporters early (doesn't require app instance).
    init_otel(service_name, service_version)

    @asynccontextmanager
    async def lifespan(app: FastAPI) -> AsyncGenerator[None, None]:  # noqa: ARG001
        """Initialize and teardown shared infrastructure (DB/Redis).

        Args:
            app: FastAPI application instance (unused; required by signature).

        Yields:
            None
        """
        init_engine_and_sessionmaker(settings)
        init_redis(settings)
        try:
            yield
        finally:
            await close_redis()
            await dispose_engine()

    # Instantiate the app after lifespan is defined
    app = FastAPI(
        title="Stacklion API",
        version=service_version,
        description=(
            "A secure, governed API platform that consolidates regulatory filings, "
            "market data, and portfolio intelligence into a single, auditable financial "
            "data backbone."
        ),
        lifespan=lifespan,
    )

    # OpenAPI contract registry first to guarantee canonical envelopes.
    attach_openapi_contract_registry(app)

    # Core middleware / CORS / errors / probes.
    _init_middlewares(app, settings)
    _add_cors(app, settings)
    _add_error_handlers(app)

    # Health and metrics endpoints (schema-hidden where appropriate).
    _add_healthz(app, settings)
    _mount_metrics(app)

    # Optional A5 routes (only if available on this branch)
    if _QUOTES_ROUTER_AVAILABLE and quotes_router is not None:
        app.include_router(quotes_router)

    # Project API routers and minimal protected probe.
    _mount_project_api(app, service_name)
    _ensure_protected_ping(app)

    # Health router: override its dependency with our concrete probe (DB + Redis via DI).
    async def _concrete_health_probe(
        db: Annotated[AsyncSession, Depends(get_db_session_dep)],
        r: Annotated[Any, Depends(get_redis_client_dep)],
    ) -> PostgresRedisProbe:
        """Provide a concrete Postgres+Redis probe to the health router.

        Args:
            db: Injected SQLAlchemy AsyncSession.
            r: Injected Redis asyncio client.

        Returns:
            A ready probe instance for the health router.
        """
        return PostgresRedisProbe(db, r)

    app.dependency_overrides[get_health_probe] = _concrete_health_probe

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
