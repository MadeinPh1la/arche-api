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
    - Pydantic v2 `BaseSettings` with `extra='forbid'` to catch unknown env.
    - Explicit field declarations with constrained types and ranges.
    - Environment enumeration for behavior toggles.
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

# Centralized logger import (graceful fallback if logging isn't initialized yet)
try:  # pragma: no cover
    from stacklion_api.infrastructure.logging.logger import logger  # type: ignore[attr-defined]
except Exception:  # pragma: no cover
    import logging

    logger = logging.getLogger("stacklion.config")


class Environment(str, Enum):
    """Deployment environment enumeration."""

    DEVELOPMENT = "development"
    STAGING = "staging"
    PRODUCTION = "production"


def _split_env(v: str | None) -> list[str]:
    """Split a comma/space-separated env var into tokens (empty on None/blank)."""
    if not v:
        return []
    # normalize both comma and whitespace; filter empties
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
    )

    database_url: str = Field(
        ...,
        description="SQLAlchemy async DB URL. Example: postgresql+asyncpg://user:pass@host:5432/db",
    )

    redis_url: str = Field(
        ...,
        description="Redis connection URL used for caching, telemetry, and rate limiting.",
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
    # Security toggles for A2
    # ---------------------------
    auth_enabled: bool = Field(
        default=False,
        description="If true, protected routes require a valid HS256 bearer token.",
        validation_alias="AUTH_ENABLED",
    )
    auth_hs256_secret: str | None = Field(
        default=None,
        description="HS256 secret used when AUTH_ENABLED=true (for CI/dev).",
        validation_alias="AUTH_HS256_SECRET",
    )

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
    # Auth (Clerk OIDC/JWT)
    # ---------------------------
    clerk_issuer: AnyHttpUrl = Field(
        ...,
        description="Clerk OIDC issuer URL (e.g., https://<sub>.clerk.accounts.dev).",
    )
    clerk_audience: str = Field(
        default="stacklion-ci",
        min_length=1,
        max_length=128,
        description="Expected JWT audience ('aud') configured in Clerk.",
    )
    clerk_jwks_ttl_seconds: int = Field(
        default=300,
        ge=60,
        le=3600,
        description="JWKS cache TTL in seconds (60–3600).",
    )

    # ---------------------------
    # Public surface (optional)
    # ---------------------------
    docs_url: AnyHttpUrl | None = Field(
        default=None,
        description="External docs base URL (e.g., https://docs.stacklion.io).",
    )
    api_base_url: AnyHttpUrl | None = Field(
        default=None,
        description="Externally visible API base URL (e.g., https://api.stacklion.io).",
    )

    # ---------------------------
    # Celery (optional)
    # ---------------------------
    celery_broker_url: str | None = Field(
        default=None,
        description="Celery broker URL (commonly Redis). Example: redis://localhost:6379/0",
    )
    celery_result_backend: str | None = Field(
        default=None,
        description="Celery result backend URL. Example: redis://localhost:6379/1",
    )

    # ---------------------------
    # Ingestion flags / CRONs (optional)
    # ---------------------------
    run_ingestion_on_startup: bool = Field(
        default=False, description="If true, run ingestion tasks at application startup."
    )
    edgar_cron: str | None = Field(default=None, description="CRON schedule for EDGAR ingestion.")
    marketstack_cron: str | None = Field(
        default=None, description="CRON schedule for MarketStack sync."
    )
    batch_ingest_cron: str | None = Field(
        default=None, description="CRON schedule for batch ingest."
    )
    ingestion_frequency: str | None = Field(
        default=None, description="Human label for ingestion cadence (e.g., '3x')."
    )

    # ---------------------------
    # MarketStack (optional)
    # ---------------------------
    marketstack_api_key: str | None = Field(default=None, description="MarketStack API key.")
    marketstack_company_fallback: Literal["warn", "skip", "fail"] | None = Field(
        default="warn", description="Fallback behavior when company resolution fails."
    )
    market_index_ticker: str | None = Field(
        default=None, description="Symbol used as market index baseline (e.g., 'SPY')."
    )

    # ---------------------------
    # Legacy local admin/API keys (dev only)
    # ---------------------------
    api_key: str | None = Field(
        default=None, description="Legacy local API key (development only)."
    )
    admin_api_key: str | None = Field(
        default=None, description="Legacy local admin API key (development only)."
    )

    # ---------------------------
    # Internal service JWT (not end-user auth)
    # ---------------------------
    jwt_secret_key: str | None = Field(
        default=None, description="HMAC secret for internal service-issued JWTs."
    )
    jwt_algorithm: str | None = Field(
        default="HS256", description="JWT algorithm for internal tokens (e.g., HS256)."
    )
    jwt_access_token_minutes: int | None = Field(
        default=60, ge=5, le=24 * 60, description="TTL (minutes) for internal tokens."
    )
    jwt_issuer: str | None = Field(default=None, description="Issuer for internal tokens, if used.")
    jwt_audience: str | None = Field(
        default=None, description="Audience for internal tokens, if used."
    )

    # ---------------------------
    # Clerk webhook (Svix) (optional)
    # ---------------------------
    clerk_webhook_secret: str | None = Field(
        default=None, description="Clerk (Svix) webhook secret for user/org events."
    )

    # ---------------------------
    # Paddle (optional)
    # ---------------------------
    paddle_env: Literal["sandbox", "live"] | None = Field(
        default=None, description="Paddle environment."
    )
    paddle_api_key: str | None = Field(default=None, description="Paddle API key.")
    paddle_webhook_secret: str | None = Field(default=None, description="Paddle webhook secret.")
    paddle_api_base_url: AnyHttpUrl | None = Field(
        default=None, description="Override for Paddle API base URL."
    )
    paddle_webhook_max_skew_seconds: int | None = Field(
        default=300, ge=60, le=900, description="Webhook timestamp tolerance (seconds)."
    )

    # ---------------------------
    # Developer API key issuance (optional)
    # ---------------------------
    api_key_pepper_b64: str | None = Field(
        default=None, description="Base64-encoded pepper used during API key hashing."
    )
    api_key_old_pepper_b64: str | None = Field(
        default=None, description="Previous pepper accepted during rotation window."
    )
    api_key_prefix_test: str | None = Field(default="sl_test_", description="Prefix for test keys.")
    api_key_prefix_live: str | None = Field(default="sl_live_", description="Prefix for live keys.")
    api_key_min_bytes: int | None = Field(
        default=32, ge=16, le=64, description="Min random bytes for key generation."
    )

    # ---------------------------
    # Compatibility / accepted env (avoid extra='forbid' failures)
    # ---------------------------
    service_name: str | None = Field(default=None, alias="SERVICE_NAME")
    service_version: str | None = Field(default=None, alias="SERVICE_VERSION")
    log_level: str | None = Field(default=None, alias="LOG_LEVEL")
    edgar_base_url: AnyHttpUrl | None = Field(default=None, alias="EDGAR_BASE_URL")
    auth_rs256_public_key_pem: str | None = Field(default=None, alias="AUTH_RS256_PUBLIC_KEY_PEM")

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
    @field_validator("cors_allow_origins", mode="before")
    @classmethod
    def _split_cors_origins(cls, v: Any) -> list[str]:
        """Normalize allowed CORS origins when pydantic supplies a raw value.

        Accepts:
            - Comma-separated string ("https://a, https://b")
            - JSON-like list ('["https://a","https://b"]')
            - Native list (["https://a","https://b"])
        """
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
        """Validate database driver is AsyncPG."""
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
            • If AUTH is enabled, an HS256 secret must be provided.
            • If rate limiting is enabled with a 'redis' backend, REDIS_URL must be set.
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

        # Auth requirements
        if self.auth_enabled and not self.auth_hs256_secret:
            raise ValueError(
                "AUTH_ENABLED=true requires AUTH_HS256_SECRET to be set for HS256 validation."
            )

        # Rate limit backend requirements
        if self.rate_limit_enabled and self.rate_limit_backend == "redis" and not self.redis_url:
            raise ValueError("RATE_LIMIT_BACKEND=redis requires REDIS_URL to be set.")

        return self


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    """Return a cached singleton `Settings` instance.

    Reads process and `.env` variables according to `model_config`, validates
    fields, applies cross-field rules, and logs a non-sensitive summary.
    """
    try:
        settings = Settings()
        logger.info(
            "Settings initialized",
            extra={
                "environment": settings.environment.value,
                "cors_count": len(settings.cors_allow_origins),
                "cors_has_wildcard": any(o == "*" for o in settings.cors_allow_origins),
                "auth_enabled": settings.auth_enabled,
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
            },
        )
        return settings
    except ValidationError as exc:
        logger.exception("Invalid application configuration")
        raise RuntimeError(f"Invalid configuration: {exc}") from exc
