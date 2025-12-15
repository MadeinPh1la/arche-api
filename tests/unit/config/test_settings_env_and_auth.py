from __future__ import annotations

import os

import pytest
from pydantic import ValidationError

from arche_api.config.settings import Environment, Settings


def _set_minimal_core_env(monkeypatch: pytest.MonkeyPatch) -> None:
    """Helper to satisfy required core settings."""
    monkeypatch.setenv(
        "DATABASE_URL",
        "postgresql+asyncpg://user:pass@localhost:5432/arche_test",
    )
    monkeypatch.setenv("REDIS_URL", "redis://localhost:6379/0")


def test_settings_accepts_test_environment_and_sets_flag(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """ENVIRONMENT=test should coerce to Environment.TEST and set STACKLION_TEST_MODE."""
    _set_minimal_core_env(monkeypatch)
    monkeypatch.setenv("ENVIRONMENT", "test")
    monkeypatch.setenv("ALLOWED_ORIGINS", "https://example.com, https://foo.bar")
    monkeypatch.delenv("STACKLION_TEST_MODE", raising=False)

    settings = Settings()

    assert settings.environment == Environment.TEST
    # Validator should have set this flag
    assert os.getenv("STACKLION_TEST_MODE") == "1"
    assert settings.cors_allow_origins == [
        "https://example.com",
        "https://foo.bar",
    ]


def test_settings_rejects_wildcard_cors_in_production(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """In production, '*' for CORS should be rejected."""
    _set_minimal_core_env(monkeypatch)
    monkeypatch.setenv("ENVIRONMENT", "production")
    monkeypatch.setenv("ALLOWED_ORIGINS", "*")

    with pytest.raises(ValidationError):
        Settings()
