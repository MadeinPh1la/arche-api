# src/stacklion_api/config/settings.py
# Copyright (c) Stacklion.
# SPDX-License-Identifier: MIT
"""
Stacklion Configuration (Pydantic Settings, v2)

Summary:
    Typed, validated application configuration for the Stacklion API. This
    module centralizes environment parsing and validation and is safe to import
    from any layer; however, only Adapters/Infrastructure should read process
    environment at runtime. Other layers should receive `Settings` via DI.

Design:
    - Pydantic v2 BaseSettings with `extra='forbid'` to catch unknown env.
    - Explicit field declarations with constrained types and ranges.
    - Environment enumeration for behavior toggles (now includes TEST).
    - Singleton accessor `get_settings()` with LRU cache.
    - Safe, structured logging (no secrets).
"""

from __future__ import annotations

import os
from enum import Enum
from functools import lru_cache
from typing import Any, Literal

from pydantic import AnyHttpUrl, Field, ValidationError, field_validator, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

# Structured logger (graceful fallback if infra logger isn't available yet)
try:  # pragma: no cover
    from stacklion_api.infrastructure.logging.logger import (
        configure_root_logging,
        get_json_logger,
    )

    configure_root_logging()
    logger = get_json_logger("stacklion.config")
except Exception:  # pragma: no cover
    import logging

    logger = logging.getLogger("stacklion.config")


class Environment(str, Enum):
    """Deployment environment enumeration (string-backed)."""

    DEVELOPMENT = "development"
    TEST = "test"
    STAGING = "staging"
    PRODUCTION = "production"


def _split_env(v: str | None) -> list[str]:
    """Split a comma/space-separated env var into tokens."""
    if not v:
        return []
    parts = [p.strip() for chunk in v.split(",") for p in chunk.split()]
    return [p for p in parts if p]


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
        description="SQLAlchemy async DB URL. Example: postgresql+asyncpg://user:pass@host:5432/db",
        validation_alias="DATABASE_URL",
    )

    redis_url: str = Field(
        ...,
        description="Redis connection URL used for caching, telemetry, and rate limiting.",
        validation_alias="REDIS_URL",
    )

    # Raw env; parse manually to avoid pydantic JSON decoding on list[str]
    cors_allow_origins_raw: str | None = Field(
        default=None,
        alias="ALLOWED_ORIGINS",
        description="Raw env for allowed CORS origins; parsed into cors_allow_origins.",
    )

    # Parsed, canonical list
    cors_allow_origins: list[str] = Field(
        default_factory=list,
        description="Allowed CORS origins. In dev, '*' is allowed. In production, '*' is rejected.",
    )

    # ---------------------------
    # Security toggles / auth modes
    # ---------------------------
    auth_enabled: bool = Field(
        default=False,
        description="Enable request auth. If true, either HS256 (dev/CI) or Clerk OIDC must be configured.",
        validation_alias="AUTH_ENABLED",
    )

    # HS256 (dev/CI) mode
    auth_hs256_secret: str | None = Field(
        default=None,
        description="HS256 secret used when AUTH_ENABLED=true and no Clerk config is provided.",
        validation_alias="AUTH_HS256_SECRET",
    )

    # Clerk OIDC (production) mode — all optional; validated conditionally
    clerk_issuer: AnyHttpUrl | None = Field(
        default=None,
        description="Clerk OIDC issuer URL (e.g., https://<sub>.clerk.accounts.dev). Required if using Clerk.",
        validation_alias="CLERK_ISSUER",
    )
    clerk_audience: str = Field(
        default="stacklion-ci",
        min_length=1,
        max_length=128,
        description="Expected JWT audience ('aud') configured in Clerk.",
        validation_alias="CLERK_AUDIENCE",
    )
    clerk_jwks_ttl_seconds: int = Field(
        default=300,
        ge=60,
        le=3600,
        description="JWKS cache TTL in seconds (60–3600).",
        validation_alias="CLERK_JWKS_TTL_SECONDS",
    )
    # Optional Clerk inputs (compatibility / overrides)
    next_public_clerk_publishable_key: str | None = Field(
        default=None,
        description="Optional Clerk publishable key for web clients.",
        validation_alias="NEXT_PUBLIC_CLERK_PUBLISHABLE_KEY",
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
    # Compatibility public key input (if you don't want JWKS)
    auth_rs256_public_key_pem: str | None = Field(
        default=None,
        description="PEM public key for RS256 validation as an alternative to JWKS.",
        validation_alias="AUTH_RS256_PUBLIC_KEY_PEM",
    )

    # ---------------------------
    # Rate limiting
    # ---------------------------
    rate_limit_enabled: bool = Field(
        default=False,
        description="Enable rate limiting middleware.",
        validation_alias="RATE_LIMIT_ENABLED",
    )
    rate_limit_backend: Literal["memory", "redis"] = Field(
        default="memory",
        description="Rate limit storage backend.",
        validation_alias="RATE_LIMIT_BACKEND",
    )
    rate_limit_burst: int = Field(
        default=5,
        ge=1,
        le=10_000,
        description="Requests allowed per window before 429.",
        validation_alias="RATE_LIMIT_BURST",
    )
    rate_limit_window_seconds: int = Field(
        default=1,
        ge=1,
        le=86_400,
        description="Size of rate limit window in seconds.",
        validation_alias="RATE_LIMIT_WINDOW_SECONDS",
    )

    # ---------------------------
    # Observability (OTEL)
    # ---------------------------
    otel_enabled: bool = Field(
        default=False,
        description="Enable OpenTelemetry instrumentation.",
        validation_alias="OTEL_ENABLED",
    )
    otel_exporter_otlp_endpoint: AnyHttpUrl | None = Field(
        default=None,
        description=(
            "OTLP endpoint for traces/metrics/logs. "
            "Examples: http://otel-collector:4318/v1/traces or http://otel-collector:4317"
        ),
        validation_alias="OTEL_EXPORTER_OTLP_ENDPOINT",
    )

    # ---------------------------
    # Public surface (optional)
    # ---------------------------
    docs_url: AnyHttpUrl | None = Field(
        default=None,
        description="External docs base URL (e.g., https://docs.stacklion.io).",
        validation_alias="DOCS_URL",
    )
    api_base_url: AnyHttpUrl | None = Field(
        default=None,
        description="Externally visible API base URL (e.g., https://api.stacklion.io).",
        validation_alias="API_BASE_URL",
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

    # ---------------------------
    # MarketStack (optional)
    # ---------------------------
    marketstack_api_key: str | None = Field(
        default=None, description="MarketStack API key.", validation_alias="MARKETSTACK_API_KEY"
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
        description="Legacy local admin API key (development only).",
        validation_alias="ADMIN_API_KEY",
    )

    # ---------------------------
    # Internal service JWT (not end-user auth)
    # ---------------------------
    jwt_secret_key: str | None = Field(
        default=None,
        description="HMAC secret for internal service-issued JWTs.",
        validation_alias="JWT_SECRET_KEY",
    )
    jwt_algorithm: str | None = Field(
        default="HS256",
        description="JWT algorithm for internal tokens (e.g., HS256).",
        validation_alias="JWT_ALGORITHM",
    )
    jwt_access_token_minutes: int | None = Field(
        default=60,
        ge=5,
        le=24 * 60,
        description="TTL (minutes) for internal tokens.",
        validation_alias="JWT_ACCESS_TOKEN_MINUTES",
    )
    jwt_issuer: str | None = Field(
        default=None,
        description="Issuer for internal tokens, if used.",
        validation_alias="JWT_ISSUER",
    )
    jwt_audience: str | None = Field(
        default=None,
        description="Audience for internal tokens, if used.",
        validation_alias="JWT_AUDIENCE",
    )

    # ---------------------------
    # Clerk webhook (Svix) (optional)
    # ---------------------------
    clerk_webhook_secret: str | None = Field(
        default=None,
        description="Clerk (Svix) webhook secret for user/org events.",
        validation_alias="CLERK_WEBHOOK_SECRET",
    )

    # ---------------------------
    # Paddle (optional)
    # ---------------------------
    paddle_env: Literal["sandbox", "live"] | None = Field(
        default=None, description="Paddle environment.", validation_alias="PADDLE_ENV"
    )
    paddle_api_key: str | None = Field(
        default=None, description="Paddle API key.", validation_alias="PADDLE_API_KEY"
    )
    paddle_webhook_secret: str | None = Field(
        default=None, description="Paddle webhook secret.", validation_alias="PADDLE_WEBHOOK_SECRET"
    )
    paddle_api_base_url: AnyHttpUrl | None = Field(
        default=None,
        description="Override for Paddle API base URL.",
        validation_alias="PADDLE_API_BASE_URL",
    )
    paddle_webhook_max_skew_seconds: int | None = Field(
        default=300,
        ge=60,
        le=900,
        description="Webhook timestamp tolerance (seconds).",
        validation_alias="PADDLE_WEBHOOK_MAX_SKEW_SECONDS",
    )

    # ---------------------------
    # Developer API key issuance (optional)
    # ---------------------------
    api_key_pepper_b64: str | None = Field(
        default=None,
        description="Base64-encoded pepper used during API key hashing.",
        validation_alias="API_KEY_PEPPER_B64",
    )
    api_key_old_pepper_b64: str | None = Field(
        default=None,
        description="Previous pepper accepted during rotation window.",
        validation_alias="API_KEY_OLD_PEPPER_B64",
    )
    api_key_prefix_test: str | None = Field(
        default="sl_test_",
        description="Prefix for test keys.",
        validation_alias="API_KEY_PREFIX_TEST",
    )
    api_key_prefix_live: str | None = Field(
        default="sl_live_",
        description="Prefix for live keys.",
        validation_alias="API_KEY_PREFIX_LIVE",
    )
    api_key_min_bytes: int | None = Field(
        default=32,
        ge=16,
        le=64,
        description="Min random bytes for key generation.",
        validation_alias="API_KEY_MIN_BYTES",
    )

    # ---------------------------
    # Compatibility / accepted env (avoid extra='forbid' failures)
    # ---------------------------
    service_name: str | None = Field(default=None, alias="SERVICE_NAME")
    service_version: str | None = Field(default=None, alias="SERVICE_VERSION")
    log_level: str | None = Field(default=None, alias="LOG_LEVEL")
    edgar_base_url: AnyHttpUrl | None = Field(default=None, alias="EDGAR_BASE_URL")

    # ---------------------------
    # Pydantic Settings config
    # ---------------------------
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="forbid",
        validate_default=True,
    )

    # ---------------------------
    # Validators
    # ---------------------------
    @field_validator("environment", mode="before")
    @classmethod
    def _accept_test_env(cls, v: object) -> object:
        """Accept ENVIRONMENT=test and keep it as 'test'; set test-mode flag."""
        if isinstance(v, str) and v.lower() == "test":
            os.environ["STACKLION_TEST_MODE"] = "1"
            return Environment.TEST.value
        return v

    @field_validator("cors_allow_origins", mode="before")
    @classmethod
    def _split_cors_origins(cls, v: Any) -> list[str]:
        """Normalize allowed CORS origins when Pydantic supplies a raw value."""
        if v is None or v == "":
            return []
        if isinstance(v, list):
            return [str(x).strip() for x in v if str(x).strip()]
        if isinstance(v, str):
            s = v.strip()
            if s.startswith("[") and s.endswith("]"):
                s = s.strip("[]")
                parts = [p.strip().strip('"').strip("'") for p in s.split(",")]
                return [p for p in parts if p]
            return [x.strip() for x in s.split(",") if x.strip()]
        raise ValueError("Invalid CORS origins format; use comma-separated string or list.")

    @model_validator(mode="after")
    def _coerce_cors_list(self) -> Settings:
        """Coerce ALLOWED_ORIGINS / CORS_ALLOW_ORIGINS into `cors_allow_origins`."""
        raw = self.cors_allow_origins_raw or os.getenv("CORS_ALLOW_ORIGINS")
        if not self.cors_allow_origins:
            self.cors_allow_origins = _split_env(raw)
        return self

    @field_validator("database_url")
    @classmethod
    def _ensure_asyncpg(cls, v: str) -> str:
        """Validate that the database driver is AsyncPG."""
        if v.startswith("postgresql://"):
            raise ValueError("Use 'postgresql+asyncpg://...' for async SQLAlchemy.")
        if not v.startswith("postgresql+asyncpg://"):
            raise ValueError("Unsupported DB driver. Expected 'postgresql+asyncpg://'.")
        return v

    @model_validator(mode="after")
    def _post_validate_security_and_env(self) -> Settings:
        """Enforce cross-field security and environment constraints.

        Rules enforced:
            • In PRODUCTION: CORS may not include '*' and all origins must be HTTPS
              (localhost is exempt for tooling).
            • If AUTH is enabled, either:
                - HS256 mode: AUTH_HS256_SECRET must be set; or
                - Clerk OIDC mode: CLERK_ISSUER and (CLERK_JWKS_URL or AUTH_RS256_PUBLIC_KEY_PEM)
                  must be provided.
            • If rate limiting is enabled with a 'redis' backend, REDIS_URL must be set.
            • If OTEL is enabled, an OTLP endpoint must be provided.
        """
        # CORS hardening
        if self.environment == Environment.PRODUCTION:
            if any(origin == "*" for origin in self.cors_allow_origins):
                raise ValueError(
                    "In production, ALLOWED_ORIGINS/CORS_ALLOW_ORIGINS cannot contain '*'."
                )
            offenders = [
                origin
                for origin in self.cors_allow_origins
                if not (origin.startswith("https://") or origin.startswith("http://localhost"))
            ]
            if offenders:
                raise ValueError(
                    "Production CORS origins must be HTTPS or localhost. Offenders: " f"{offenders}"
                )

        # Auth requirements (conditional)
        if self.auth_enabled:
            hs256_ok = bool(self.auth_hs256_secret)
            clerk_ok = bool(
                self.clerk_issuer and (self.clerk_jwks_url or self.auth_rs256_public_key_pem)
            )
            if not (hs256_ok or clerk_ok):
                raise ValueError(
                    "AUTH_ENABLED=true requires either: "
                    "HS256 mode (set AUTH_HS256_SECRET), or Clerk OIDC mode "
                    "(set CLERK_ISSUER and CLERK_JWKS_URL or AUTH_RS256_PUBLIC_KEY_PEM)."
                )

        # Rate limit backend requirements
        if self.rate_limit_enabled and self.rate_limit_backend == "redis" and not self.redis_url:
            raise ValueError("RATE_LIMIT_BACKEND=redis requires REDIS_URL to be set.")

        # OTEL requirements
        if self.otel_enabled and not self.otel_exporter_otlp_endpoint:
            raise ValueError("OTEL_ENABLED=true requires OTEL_EXPORTER_OTLP_ENDPOINT to be set.")

        return self


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    """Return a cached singleton `Settings` instance."""
    try:
        settings = Settings()
        logger.info(
            "Settings initialized",
            extra={
                "environment": settings.environment.value,
                "test_mode": os.getenv("STACKLION_TEST_MODE") == "1",
                "cors_count": len(settings.cors_allow_origins),
                "cors_has_wildcard": any(o == "*" for o in settings.cors_allow_origins),
                "auth_enabled": settings.auth_enabled,
                "auth_mode": (
                    "hs256"
                    if settings.auth_hs256_secret
                    else ("clerk" if settings.clerk_issuer else "none")
                ),
                "rate_limit": {
                    "enabled": settings.rate_limit_enabled,
                    "backend": settings.rate_limit_backend,
                    "burst": settings.rate_limit_burst,
                    "window_s": settings.rate_limit_window_seconds,
                },
                "jwks_ttl": settings.clerk_jwks_ttl_seconds,
                "docs_url_set": bool(settings.docs_url),
                "api_base_url_set": bool(settings.api_base_url),
                "has_celery": bool(settings.celery_broker_url and settings.celery_result_backend),
                "ingest_on_start": settings.run_ingestion_on_startup,
                "paddle_env": settings.paddle_env if settings.paddle_env else None,
                "otel_enabled": settings.otel_enabled,
                "otel_endpoint_set": bool(settings.otel_exporter_otlp_endpoint),
            },
        )
        return settings
    except ValidationError as exc:
        logger.exception("Invalid application configuration")
        raise RuntimeError(f"Invalid configuration: {exc}") from exc
