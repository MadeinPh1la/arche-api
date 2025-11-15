# Copyright (c) Stacklion.
# SPDX-License-Identifier: MIT
"""
Auth Feature Settings (Adapters-facing view)

Summary:
    A minimal, typed projection of authentication-related toggles/secrets for
    adapters/infrastructure. Keeps infra decoupled from the full Settings surface.

Behavior:
    • If AUTH_ENABLED is explicitly set in the environment, use it (and
      AUTH_HS256_SECRET) — this avoids cross-test caching via get_settings().
    • Otherwise, fall back to the canonical application settings.

Notes:
    • No logging/printing of secrets.
"""

from __future__ import annotations

import os
from typing import Any

from pydantic import BaseModel, Field

import stacklion_api.config.settings as _settings_module

__all__ = ["AuthSettings", "get_auth_settings"]


class AuthSettings(BaseModel):
    """Narrow view of auth configuration used by adapters/infrastructure.

    Attributes:
        enabled:
            When true, protected routes must validate a bearer token.
        hs256_secret:
            Shared secret for HS256 validation in dev/CI simple mode.
            May be None if auth is disabled.
    """

    enabled: bool = Field(default=False)
    hs256_secret: str | None = Field(default=None)


def _to_bool(val: str | None) -> bool:
    """Return True for common truthy strings ('1','true','yes','on')."""
    return (val or "").strip().lower() in {"1", "true", "yes", "on"}


def get_settings() -> Any:
    """Thin wrapper around the global settings accessor.

    Defined here so tests can reliably monkeypatch
    ``stacklion_api.config.features.auth.get_settings`` and have
    `get_auth_settings()` respect it.
    """
    return _settings_module.get_settings()


def get_auth_settings() -> AuthSettings:
    """Return current auth config, honoring env overrides (test-friendly).

    Reads AUTH_ENABLED / AUTH_HS256_SECRET directly from the environment when
    AUTH_ENABLED is explicitly set. Otherwise falls back to application settings.

    Returns:
        AuthSettings: Minimal auth configuration for adapters/infrastructure.
    """
    raw_enabled = os.getenv("AUTH_ENABLED")
    if raw_enabled is not None:
        # Explicit override present — use env for both fields.
        return AuthSettings(
            enabled=_to_bool(raw_enabled),
            hs256_secret=os.getenv("AUTH_HS256_SECRET"),
        )

    # Fallback to canonical application settings (cached singleton).
    s = get_settings()
    return AuthSettings(enabled=s.auth_enabled, hs256_secret=s.auth_hs256_secret)
