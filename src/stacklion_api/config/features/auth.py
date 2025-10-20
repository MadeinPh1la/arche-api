# Copyright (c) Stacklion.
# SPDX-License-Identifier: MIT
"""
Auth Feature Settings (Adapters-facing view)

Summary:
    A minimal, typed projection of authentication-related toggles/secrets for
    adapters/infrastructure. This keeps infra decoupled from the full Settings
    surface and avoids importing heavy modules in request-time code.

Design:
    * Pulls from the canonical application settings via `get_settings()`.
    * Exposes a small `AuthSettings` model used by FastAPI dependencies.
    * Contains no business logic and never logs/prints secrets.

Usage:
    from stacklion_api.config.features.auth import get_auth_settings

    def dependency(
        cfg: AuthSettings = Depends(get_auth_settings),
    ):
        if cfg.enabled:
            ...
"""

from __future__ import annotations

from pydantic import BaseModel, Field

from stacklion_api.config.settings import get_settings

__all__ = ["AuthSettings", "get_auth_settings"]


class AuthSettings(BaseModel):
    """Narrow view of auth configuration used by adapters/infrastructure.

    Attributes:
        enabled: When true, protected routes must validate a bearer token.
        hs256_secret: Shared secret for HS256 validation in dev/CI simple mode.
                      May be None if auth is disabled.
    """

    enabled: bool = Field(default=False)
    hs256_secret: str | None = Field(default=None)


def get_auth_settings() -> AuthSettings:
    """Return the current authentication feature settings.

    Pulls from the canonical application settings (cached singleton) and maps
    only the fields required by infra/auth dependencies.

    Returns:
        AuthSettings: Minimal auth configuration for adapters/infrastructure.
    """
    s = get_settings()
    return AuthSettings(enabled=s.auth_enabled, hs256_secret=s.auth_hs256_secret)
