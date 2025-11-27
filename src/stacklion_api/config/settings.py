# src/stacklion_api/config/settings.py
# Copyright (c) Stacklion.
# SPDX-License-Identifier: MIT
"""Stacklion Configuration (Pydantic Settings, v2)

Summary:
    Typed, validated application configuration for the Stacklion API. This
    module centralizes environment parsing and validation and is safe to import
    from any layer; however, only Adapters/Infrastructure should read process
    environment at runtime. Other layers should receive `Settings` via DI.

Design:
    - Pydantic v2 BaseSettings with `extra='forbid'` to catch unknown env.
    - Explicit field declarations with constrained types and ranges.
    - Environment enumeration for behavior toggles (includes TEST).
    - Singleton accessor `get_settings()` with LRU cache.
    - Safe, structured logging (no secrets).
"""

from __future__ import annotations

import logging
import os
from enum import Enum
from functools import lru_cache
from typing import Literal

from pydantic import AnyHttpUrl, Field, SecretStr, ValidationError, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

# Local logger (global logging configuration is owned by bootstrap())
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


class Environment(str, Enum):
    """Logical deployment environment.

    This is a thin classification used for coarse-grained behavior toggles.
    """

    DEVELOPMENT = "development"
    TEST = "test"
    CI = "ci"
    STAGING = "staging"
    PRODUCTION = "production"


class PaddleEnvironment(str, Enum):
    """Paddle environment enumeration."""

    SANDBOX = "sandbox"
    PRODUCTION = "production"


class Settings(BaseSettings):
    """Typed application configuration for Stacklion.

    This is the canonical, explicit, and strict settings object. Adapters and
    Infrastructure may read environment variables; other layers should receive
    this object through dependency injection.
    """

    # ---------------------------
    # Core environment & platforms
    # ---------------------------
    environment: Environment = Field(
        default=Environment.DEVELOPMENT,
        description="Logical deployment environment.",
        validation_alias="ENVIRONMENT",
    )

    database_url: str = Field(
        ...,
        description=(
            "SQLAlchemy async DB URL. Example: " "postgresql+asyncpg://user:pass@host:5432/db"
        ),
        validation_alias="DATABASE_URL",
    )

    db_schema: str | None = Field(
        default="public",
        description="Default PostgreSQL schema for core tables.",
        validation_alias="DB_SCHEMA",
    )

    redis_url: str = Field(
        ...,
        description="Redis connection URL used for caching, telemetry, and rate limiting.",
        validation_alias="REDIS_URL",
    )

    redis_health_check_interval_s: int = Field(
        default=15,
        ge=1,
        le=3600,
        description="Health check interval for Redis clients in seconds.",
        validation_alias="REDIS_HEALTH_CHECK_INTERVAL_S",
    )
    redis_socket_timeout_s: float = Field(
        default=3.0,
        ge=0.1,
        le=60.0,
        description="Socket timeout in seconds for Redis commands.",
        validation_alias="REDIS_SOCKET_TIMEOUT_S",
    )
    redis_socket_connect_timeout_s: float = Field(
        default=3.0,
        ge=0.1,
        le=60.0,
        description="Socket connect timeout in seconds for Redis.",
        validation_alias="REDIS_SOCKET_CONNECT_TIMEOUT_S",
    )

    # Raw env for CORS; we compute the parsed list in a model validator.
    cors_allow_origins_raw: str | None = Field(
        default=None,
        description="Raw env for allowed CORS origins (comma-separated).",
        validation_alias="ALLOWED_ORIGINS",
    )

    cors_allow_origins: list[str] = Field(
        default_factory=list,
        description=(
            "Allowed CORS origins. Derived from ALLOWED_ORIGINS. "
            "In development/test, '*' is allowed; in production-like envs, '*' is rejected."
        ),
    )

    # ---------------------------
    # Security toggles / auth modes
    # ---------------------------
    auth_enabled: bool = Field(
        default=False,
        description=(
            "Enable request auth. If true, either HS256 (dev/CI) or Clerk OIDC "
            "must be configured."
        ),
        validation_alias="AUTH_ENABLED",
    )

    # HS256 (dev/CI) mode
    auth_hs256_secret: str | None = Field(
        default=None,
        description="HS256 secret used when AUTH_ENABLED=true and no Clerk config is provided.",
        validation_alias="AUTH_HS256_SECRET",
    )

    auth_algorithm: str = Field(
        default="HS256",
        description="JWT signing algorithm used in HS256 dev/test mode.",
        validation_alias="AUTH_ALGORITHM",
    )

    # Clerk / OIDC mode
    clerk_frontend_api: str | None = Field(
        default=None,
        description="Clerk frontend API base URL, used to validate tokens issued for this frontend.",
        validation_alias="CLERK_FRONTEND_API",
    )
    clerk_publisher: str | None = Field(
        default=None,
        description="Expected 'azp' (authorized party) / publisher claim for Clerk tokens.",
        validation_alias="CLERK_PUBLISHER",
    )
    clerk_jwks_cache_seconds: int = Field(
        default=300,
        ge=60,
        le=24 * 60 * 60,
        description="TTL for JWKS cache used when validating Clerk-issued tokens.",
        validation_alias="CLERK_JWKS_CACHE_SECONDS",
    )
    clerk_jwks_ttl_seconds: int = Field(
        default=300,
        ge=60,
        le=24 * 60 * 60,
        description="TTL for Clerk JWKS entries in Redis.",
        validation_alias="CLERK_JWKS_TTL_SECONDS",
    )
    clerk_secret_key: str | None = Field(
        default=None,
        description="Optional Clerk server secret (not required if using JWKS only).",
        validation_alias="CLERK_SECRET_KEY",
    )
    clerk_jwks_url: AnyHttpUrl | None = Field(
        default=None,
        description="Optional explicit JWKS URL override for Clerk (rarely needed).",
        validation_alias="CLERK_JWKS_URL",
    )

    clerk_webhook_secret: str | None = Field(
        default=None,
        description="Shared secret used to validate Clerk webhooks.",
        validation_alias="CLERK_WEBHOOK_SECRET",
    )

    # Compatibility public key input (if you don't want JWKS)
    auth_rs256_public_key_pem: str | None = Field(
        default=None,
        description="PEM public key for RS256 validation as an alternative to JWKS.",
        validation_alias="AUTH_RS256_PUBLIC_KEY_PEM",
    )

    # --- Legacy / frontend-oriented Clerk inputs (accepted, not used by API) ---
    next_public_clerk_publishable_key: str | None = Field(
        default=None,
        description=(
            "Frontend Clerk publishable key (NEXT_PUBLIC_CLERK_PUBLISHABLE_KEY). "
            "Accepted to avoid extra_forbid when sharing env files with the frontend; "
            "not used by the API runtime."
        ),
        validation_alias="NEXT_PUBLIC_CLERK_PUBLISHABLE_KEY",
    )
    clerk_issuer: str | None = Field(
        default=None,
        description=(
            "Clerk issuer/issuer URL (CLERK_ISSUER). Accepted for compatibility with "
            "shared env; not used directly by the API runtime."
        ),
        validation_alias="CLERK_ISSUER",
    )
    clerk_audience: str | None = Field(
        default=None,
        description=(
            "Expected Clerk audience (CLERK_AUDIENCE). Accepted for compatibility with "
            "shared env; not used directly by the API runtime."
        ),
        validation_alias="CLERK_AUDIENCE",
    )

    # ---------------------------
    # OpenAPI / docs
    # ---------------------------
    docs_url: str | None = Field(
        default="/docs",
        description="Swagger UI docs URL. Set to None to disable interactive docs.",
        validation_alias="DOCS_URL",
    )
    redoc_url: str | None = Field(
        default=None,
        description="ReDoc docs URL. Set to None to disable ReDoc.",
        validation_alias="REDOC_URL",
    )
    openapi_url: str | None = Field(
        default="/openapi.json",
        description="OpenAPI JSON schema URL. Set to None to disable OpenAPI exposure.",
        validation_alias="OPENAPI_URL",
    )

    # ---------------------------
    # Service identity / metadata
    # ---------------------------
    service_name: str | None = Field(
        default="stacklion-api",
        description="Logical service name for logging and tracing.",
        validation_alias="SERVICE_NAME",
    )
    service_version: str | None = Field(
        default=None,
        description="Service version used for logging and tracing.",
        validation_alias="SERVICE_VERSION",
    )
    api_base_url: AnyHttpUrl | None = Field(
        default=None,
        description=(
            "Public base URL for the Stacklion HTTP API (used in links, docs, "
            "and as a fallback for MCP→HTTP calls when MCP_HTTP_BASE_URL is unset)."
        ),
        validation_alias="API_BASE_URL",
    )

    # ---------------------------
    # MCP / internal HTTP client
    # ---------------------------
    mcp_http_base_url: AnyHttpUrl | None = Field(
        default=None,
        description=(
            "Optional override base URL for MCP→HTTP API calls. If not set, "
            "api_base_url is used, then http://127.0.0.1:8000 as a final fallback."
        ),
        validation_alias="MCP_HTTP_BASE_URL",
    )
    mcp_http_api_key: SecretStr | None = Field(
        default=None,
        description=(
            "API key used for MCP→HTTP API calls, sent as X-Api-Key. "
            "If both mcp_http_bearer_token and mcp_http_api_key are set, "
            "the bearer token takes precedence."
        ),
        validation_alias="MCP_HTTP_API_KEY",
    )
    mcp_http_bearer_token: SecretStr | None = Field(
        default=None,
        description=(
            "Bearer token used for MCP→HTTP API calls, sent as Authorization: "
            "Bearer <token>. If set, this takes precedence over mcp_http_api_key."
        ),
        validation_alias="MCP_HTTP_BEARER_TOKEN",
    )

    # ---------------------------
    # Logging
    # ---------------------------
    log_level: str | None = Field(
        default=None,
        description="Override log level (e.g., 'DEBUG', 'INFO'). If not set, defaults are used.",
        validation_alias="LOG_LEVEL",
    )

    # ---------------------------
    # OTEL / observability
    # ---------------------------
    otel_enabled: bool = Field(
        default=False,
        description="Enable OpenTelemetry tracing and metrics exporters.",
        validation_alias="OTEL_ENABLED",
    )
    otel_exporter_otlp_endpoint: AnyHttpUrl | None = Field(
        default=None,
        description="OTLP endpoint for OTEL exporters (traces/metrics).",
        validation_alias="OTEL_EXPORTER_OTLP_ENDPOINT",
    )

    # ---------------------------
    # Rate limiting
    # ---------------------------
    rate_limit_enabled: bool = Field(
        default=False,
        description="Enable global rate limiting.",
        validation_alias="RATE_LIMIT_ENABLED",
    )
    rate_limit_backend: str = Field(
        default="redis",
        description="Backend used for rate limiting (e.g., 'redis', 'memory').",
        validation_alias="RATE_LIMIT_BACKEND",
    )
    rate_limit_window_seconds: int = Field(
        default=60,
        ge=1,
        le=24 * 60 * 60,
        description="Rate limiting window size in seconds.",
        validation_alias="RATE_LIMIT_WINDOW_SECONDS",
    )
    rate_limit_burst: int = Field(
        default=60,
        ge=1,
        le=10_000,
        description="Maximum number of requests per key in a single window.",
        validation_alias="RATE_LIMIT_BURST",
    )

    # ---------------------------
    # Idempotency
    # ---------------------------
    idempotency_enabled: bool = Field(
        default=True,
        description="Enable HTTP idempotency middleware for write operations.",
        validation_alias="IDEMPOTENCY_ENABLED",
    )
    idempotency_ttl_seconds: int = Field(
        default=86_400,
        ge=1,
        le=7 * 24 * 60 * 60,
        description="Idempotency dedupe window in seconds (default 24 hours).",
        validation_alias="IDEMPOTENCY_TTL_SECONDS",
    )

    # ---------------------------
    # Paddle / billing
    # ---------------------------
    paddle_env: PaddleEnvironment | None = Field(
        default=None,
        description="Paddle environment (sandbox/production).",
        validation_alias="PADDLE_ENV",
    )
    paddle_webhook_secret: str | None = Field(
        default=None,
        description="Paddle webhook shared secret.",
        validation_alias="PADDLE_WEBHOOK_SECRET",
    )

    # ---------------------------
    # Celery (optional)
    # ---------------------------
    celery_broker_url: str | None = Field(
        default=None,
        description="Celery broker URL (commonly Redis). Example: redis://localhost:6379/0",
        validation_alias="CELERY_BROKER_URL",
    )
    celery_result_backend: str | None = Field(
        default=None,
        description="Celery result backend URL. Example: redis://localhost:6379/1",
        validation_alias="CELERY_RESULT_BACKEND",
    )

    # ---------------------------
    # Ingestion flags / CRONs (optional)
    # ---------------------------
    run_ingestion_on_startup: bool = Field(
        default=False,
        description="If true, run ingestion tasks at application startup.",
        validation_alias="RUN_INGESTION_ON_STARTUP",
    )
    edgar_cron: str | None = Field(
        default=None,
        description="CRON schedule for EDGAR ingestion.",
        validation_alias="EDGAR_CRON",
    )
    marketstack_cron: str | None = Field(
        default=None,
        description="CRON schedule for MarketStack sync.",
        validation_alias="MARKETSTACK_CRON",
    )
    batch_ingest_cron: str | None = Field(
        default=None,
        description="CRON schedule for batch ingest.",
        validation_alias="BATCH_INGEST_CRON",
    )
    ingestion_frequency: str | None = Field(
        default=None,
        description="Human label for ingestion cadence (e.g., '3x').",
        validation_alias="INGESTION_FREQUENCY",
    )

    edgar_base_url: str = Field(
        default="https://data.sec.gov",
        description="Base URL for SEC EDGAR data APIs.",
        validation_alias="EDGAR_BASE_URL",
    )

    # ---------------------------
    # MarketStack (optional)
    # ---------------------------
    marketstack_base_url: str = Field(
        default="https://api.marketstack.com/v2",
        description="MarketStack base URL used by HTTP clients and ingest.",
        validation_alias="MARKETSTACK_BASE_URL",
    )
    marketstack_timeout_s: float = Field(
        default=8.0,
        ge=0.1,
        le=60.0,
        description="Per-request timeout in seconds for MarketStack HTTP calls.",
        validation_alias="MARKETSTACK_TIMEOUT_S",
    )
    marketstack_max_retries: int = Field(
        default=4,
        ge=0,
        le=10,
        description="Max retries for MarketStack HTTP calls.",
        validation_alias="MARKETSTACK_MAX_RETRIES",
    )

    marketstack_api_key: str | None = Field(
        default=None,
        description="MarketStack API key.",
        validation_alias="MARKETSTACK_API_KEY",
    )
    marketstack_company_fallback: Literal["warn", "skip", "fail"] | None = Field(
        default="warn",
        description="Fallback behavior when company resolution fails.",
        validation_alias="MARKETSTACK_COMPANY_FALLBACK",
    )
    market_index_ticker: str | None = Field(
        default=None,
        description="Symbol used as market index baseline (e.g., 'SPY').",
        validation_alias="MARKET_INDEX_TICKER",
    )

    # ---------------------------
    # Legacy local admin/API keys (dev only)
    # ---------------------------
    api_key: str | None = Field(
        default=None,
        description="Legacy local API key (development only).",
        validation_alias="API_KEY",
    )
    admin_api_key: str | None = Field(
        default=None,
        description="Legacy admin API key (development only).",
        validation_alias="ADMIN_API_KEY",
    )

    model_config = SettingsConfigDict(
        env_file=".env",
        extra="forbid",
        case_sensitive=False,
    )

    @model_validator(mode="after")
    def _compute_cors_and_auth(self) -> Settings:
        """Compute CORS list and validate auth configuration.

        Returns:
            Settings: The validated and possibly mutated settings instance.

        Raises:
            ValueError: If CORS or auth-related invariants are violated.
        """
        # --- CORS parsing from raw string ---
        raw = (self.cors_allow_origins_raw or "").strip()
        if not raw:
            self.cors_allow_origins = []
        else:
            entries = [e.strip() for e in raw.split(",") if e.strip()]
            if entries:
                if any(e == "*" for e in entries) and self.environment not in (
                    Environment.DEVELOPMENT,
                    Environment.TEST,
                ):
                    raise ValueError(
                        "'*' CORS origin is only allowed in development/test environments.",
                    )
                self.cors_allow_origins = entries
            else:
                self.cors_allow_origins = []

        # --- Auth cross-field validation ---
        if self.auth_enabled:
            has_hs256 = bool(self.auth_hs256_secret)
            has_clerk = bool(self.clerk_frontend_api and self.clerk_publisher)
            if not (has_hs256 or has_clerk):
                raise ValueError(
                    "AUTH_ENABLED is true but neither HS256 nor Clerk configuration is present. "
                    "Set AUTH_HS256_SECRET or configure Clerk "
                    "(CLERK_FRONTEND_API + CLERK_PUBLISHER).",
                )

        return self

    @model_validator(mode="after")
    def _validate_environment_side_effects(self) -> Settings:
        """Apply environment-related side effects.

        In particular, force STACKLION_TEST_MODE=1 when ENVIRONMENT=test to
        ensure consistent deterministic behavior across tests.

        Returns:
            Settings: The validated and possibly mutated settings instance.
        """
        if self.environment is Environment.TEST and os.getenv("STACKLION_TEST_MODE") != "1":
            os.environ["STACKLION_TEST_MODE"] = "1"
            logger.info("STACKLION_TEST_MODE enabled due to ENVIRONMENT=test")

        return self

    # --------------------------------------------------------------------- #
    # MCP helpers
    # --------------------------------------------------------------------- #
    def mcp_resolved_http_base_url(self) -> str:
        """Return the effective base URL used for MCP→HTTP calls.

        Resolution order:
            1. mcp_http_base_url (MCP_HTTP_BASE_URL), if set.
            2. api_base_url (API_BASE_URL), if set.
            3. http://127.0.0.1:8000 as a final local fallback.

        Returns:
            A string base URL suitable for use by MCP HTTP clients.
        """
        if self.mcp_http_base_url is not None:
            return str(self.mcp_http_base_url)

        if self.api_base_url is not None:
            return str(self.api_base_url)

        # Final fallback for local/dev and tests.
        return "http://127.0.0.1:8000"


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    """Return a cached singleton `Settings` instance.

    Returns:
        Settings: Validated application settings.

    Raises:
        RuntimeError: If configuration is invalid.
    """
    try:
        settings = Settings()
        logger.info(
            "Settings initialized",
            extra={
                "environment": settings.environment.value,
                "test_mode": os.getenv("STACKLION_TEST_MODE") == "1",
                "cors_count": len(settings.cors_allow_origins),
                "cors_has_wildcard": any(o == "*" for o in settings.cors_allow_origins),
                "redis_url_set": bool(settings.redis_url),
                "docs": {
                    "docs_url": settings.docs_url,
                    "redoc_url": settings.redoc_url,
                    "openapi_url": settings.openapi_url,
                },
                "auth": {
                    "enabled": settings.auth_enabled,
                    "has_hs256": bool(settings.auth_hs256_secret),
                    "has_clerk": bool(settings.clerk_frontend_api and settings.clerk_publisher),
                },
                "rate_limit": {
                    "enabled": settings.rate_limit_enabled,
                    "backend": settings.rate_limit_backend,
                    "window": settings.rate_limit_window_seconds,
                    "burst": settings.rate_limit_burst,
                },
                "idempotency": {
                    "enabled": settings.idempotency_enabled,
                    "ttl_seconds": settings.idempotency_ttl_seconds,
                },
                "paddle_env": settings.paddle_env if settings.paddle_env else None,
                "otel_enabled": settings.otel_enabled,
                "otel_endpoint_set": bool(settings.otel_exporter_otlp_endpoint),
                "db_schema": settings.db_schema,
                "marketstack_base_url": settings.marketstack_base_url,
                "marketstack_timeout_s": settings.marketstack_timeout_s,
                "marketstack_max_retries": settings.marketstack_max_retries,
                "redis_health_check_interval_s": settings.redis_health_check_interval_s,
                "redis_socket_timeout_s": settings.redis_socket_timeout_s,
                "redis_socket_connect_timeout_s": settings.redis_socket_connect_timeout_s,
                "edgar_base_url": str(settings.edgar_base_url),
                "mcp_http": {
                    "base_url_raw": (
                        str(settings.mcp_http_base_url) if settings.mcp_http_base_url else None
                    ),
                    "resolved_base_url": settings.mcp_resolved_http_base_url(),
                    "has_api_key": settings.mcp_http_api_key is not None,
                    "has_bearer_token": settings.mcp_http_bearer_token is not None,
                },
            },
        )
        return settings
    except ValidationError as exc:
        logger.exception("Invalid application configuration")
        raise RuntimeError(f"Invalid configuration: {exc}") from exc
