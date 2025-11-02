# Copyright (c) Stacklion.
# SPDX-License-Identifier: MIT
"""
Application Entry (Adapters Bootstrap)

Synopsis:
    FastAPI bootstrap that wires middleware, the OpenAPI Contract Registry, and all
    routers. Provides an application factory (`create_app`) and a module-level
    eager app (`app`) for tooling and snapshot tests.
"""

from __future__ import annotations

import os
from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager
from typing import Any, cast

import httpx
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from starlette.middleware.gzip import GZipMiddleware

from stacklion_api.adapters.controllers.historical_quotes_controller import (
    HistoricalQuotesController,
)
from stacklion_api.adapters.presenters.market_data_presenter import MarketDataPresenter
from stacklion_api.adapters.routers.health_router import (
    get_health_probe as _get_probe_dep,
)
from stacklion_api.adapters.routers.health_router import (
    router as health_router,
)
from stacklion_api.adapters.routers.historical_quotes_router import (
    HistoricalQuotesRouter,
)
from stacklion_api.adapters.routers.metrics_router import router as metrics_router
from stacklion_api.adapters.routers.openapi_registry import (
    attach_openapi_contract_registry,
)
from stacklion_api.adapters.routers.protected_router import get_router as get_protected_router
from stacklion_api.application.interfaces.cache_port import CachePort
from stacklion_api.application.use_cases.quotes.get_historical_quotes import (
    GetHistoricalQuotesUseCase,
)
from stacklion_api.config.settings import Settings, get_settings
from stacklion_api.infrastructure.caching.json_cache import RedisJsonCache
from stacklion_api.infrastructure.caching.redis_client import close_redis, init_redis
from stacklion_api.infrastructure.database.session import (
    dispose_engine,
    init_engine_and_sessionmaker,
)
from stacklion_api.infrastructure.external_apis.marketstack.client import MarketstackGateway
from stacklion_api.infrastructure.external_apis.marketstack.settings import MarketstackSettings
from stacklion_api.infrastructure.logging.logger import configure_root_logging, get_json_logger
from stacklion_api.infrastructure.middleware.access_log import AccessLogMiddleware
from stacklion_api.infrastructure.middleware.metrics import (
    PromMetricsMiddleware,  # optional extra counters
)
from stacklion_api.infrastructure.middleware.rate_limit import RateLimitMiddleware

# Middlewares
from stacklion_api.infrastructure.middleware.request_id import RequestIdMiddleware
from stacklion_api.infrastructure.middleware.request_metrics import RequestLatencyMiddleware
from stacklion_api.infrastructure.middleware.security_headers import SecurityHeadersMiddleware
from stacklion_api.infrastructure.observability.metrics import (
    READYZ_DB_LATENCY,
    READYZ_REDIS_LATENCY,
)

# OTEL init (graceful no-op if env not enabled)
try:
    from stacklion_api.infrastructure.observability.otel import init_otel
except Exception:  # pragma: no cover

    def init_otel(*_args: object, **_kwargs: object) -> None:
        return


configure_root_logging()
logger = get_json_logger(__name__)


@asynccontextmanager
async def runtime_lifespan(app: FastAPI) -> AsyncGenerator[None, None]:
    """Initialize and teardown shared infrastructure (DB/Redis, HTTP clients)."""
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

        await close_redis()
        await dispose_engine()


def _attach_middlewares(app: FastAPI, settings: Settings) -> None:
    """Attach core middleware in the recommended order."""
    app.add_middleware(RequestIdMiddleware)
    app.add_middleware(AccessLogMiddleware)

    # Canonical server latency histogram (required by tests):
    # emits http_server_request_duration_seconds{le="..."} buckets.
    app.add_middleware(RequestLatencyMiddleware)

    # Optional additional counters (http_requests_total/http_request_duration_seconds)
    app.add_middleware(PromMetricsMiddleware)

    app.add_middleware(SecurityHeadersMiddleware)

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

    app.add_middleware(GZipMiddleware, minimum_size=1024)


def _attach_cors(app: FastAPI, settings: Settings) -> None:
    """Attach CORS with explicit exposed headers if configured."""
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


def create_app() -> FastAPI:
    """Create and configure the FastAPI application.

    Returns:
        FastAPI: Fully configured application.
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

    if not hasattr(app.state, "http_client"):
        app.state.http_client = httpx.AsyncClient()

    # Contract registry *first* to stabilize OpenAPI snapshot
    attach_openapi_contract_registry(app)

    _attach_middlewares(app, settings)
    _attach_cors(app, settings)

    # /metrics endpoint
    app.include_router(metrics_router)

    # mount protected router
    app.include_router(get_protected_router())

    # Health endpoints (expose /health/z and /health/ready)
    app.include_router(health_router, prefix="/health")

    # Record readiness histograms even with the default no-op probe
    class _MetricsOnlyProbe:
        async def db(self) -> tuple[bool, str | None]:
            READYZ_DB_LATENCY.observe(0.001)
            return False, "no db probe configured"

        async def redis(self) -> tuple[bool, str | None]:
            READYZ_REDIS_LATENCY.observe(0.001)
            return False, "no redis probe configured"

    app.dependency_overrides[_get_probe_dep] = lambda: _MetricsOnlyProbe()

    # Simple liveness used by rate-limit tests
    @app.get("/healthz")
    async def _healthz() -> dict[str, str]:
        return {"status": "ok"}

    # A6: Historical Quotes wiring (unchanged from your working version)
    http_client: httpx.AsyncClient = cast(httpx.AsyncClient, app.state.http_client)

    class _InMemoryCache(CachePort):
        def __init__(self) -> None:
            self._store: dict[str, Any] = {}

        async def get_json(self, key: str) -> Any | None:
            return self._store.get(key)

        async def set_json(self, key: str, value: Any, ttl: int | None = None) -> None:
            self._store[key] = value

    test_mode = (
        os.getenv("STACKLION_TEST_MODE") == "1"
        or os.getenv("ENVIRONMENT", "").lower() == "test"
        or ("PYTEST_CURRENT_TEST" in os.environ)
    )
    cache_port: CachePort = _InMemoryCache() if test_mode else RedisJsonCache(namespace="md:v1")

    ms_cfg = MarketstackSettings(
        base_url=getattr(settings, "marketstack_base_url", "https://api.marketstack.com/v1"),
        access_key=(
            getattr(settings, "marketstack_access_key", None)
            or os.getenv("MARKETSTACK_ACCESS_KEY")
            or "test_key"
        ),
        timeout_s=getattr(settings, "marketstack_timeout_s", 2.0),
        max_retries=getattr(settings, "marketstack_max_retries", 0),
    )
    marketstack = MarketstackGateway(http_client, ms_cfg)
    get_hist_uc = GetHistoricalQuotesUseCase(cache=cache_port, gateway=marketstack)
    presenter = MarketDataPresenter()
    controller = HistoricalQuotesController(get_hist_uc)
    hist_router = HistoricalQuotesRouter(controller=controller, presenter=presenter)
    app.include_router(hist_router.router)

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
