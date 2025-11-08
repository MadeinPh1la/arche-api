from __future__ import annotations

import pytest
from pydantic import ValidationError

# The package is installed editable ("-e ."), so import from the real package root,
# not "src.stacklion_api".
from stacklion_api.config.settings import Environment, Settings


def test_settings_read_from_environment(monkeypatch: pytest.MonkeyPatch) -> None:
    """Settings should hydrate deterministically from environment variables."""
    monkeypatch.setenv("ENVIRONMENT", "test")
    monkeypatch.setenv(
        "DATABASE_URL",
        "postgresql+asyncpg://postgres:postgres@localhost:5432/stacklion_test",
    )
    monkeypatch.setenv("REDIS_URL", "redis://localhost:6379/0")
    monkeypatch.setenv("JWT_ISSUER", "stacklion-test")

    s = Settings()

    assert s.environment == Environment.TEST
    assert "postgresql+asyncpg://" in s.database_url
    assert s.redis_url.startswith("redis://")
    # Optional if present in your model:
    if hasattr(s, "jwt_issuer"):
        assert s.jwt_issuer == "stacklion-test"


def test_settings_forbid_extra_fields() -> None:
    """Model should reject unexpected fields (EQS: ConfigDict(extra='forbid'))."""
    with pytest.raises((ValidationError, TypeError)):
        Settings.model_validate(  # type: ignore[attr-defined]
            {
                "environment": "test",
                "database_url": "postgresql+asyncpg://example",
                "redis_url": "redis://example/0",
                "unexpected_field": "boom",
            }
        )
