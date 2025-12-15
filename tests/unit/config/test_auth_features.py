from __future__ import annotations

import os

import pytest

from arche_api.config.features.auth import AuthSettings, get_auth_settings
from arche_api.config.settings import get_settings as get_app_settings


def _clear_auth_env(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("AUTH_ENABLED", raising=False)
    monkeypatch.delenv("AUTH_HS256_SECRET", raising=False)


@pytest.mark.usefixtures("_auth_env_isolated")
def test_auth_settings_env_override_enabled_true(monkeypatch: pytest.MonkeyPatch) -> None:
    """When AUTH_ENABLED is set, env should drive both fields."""
    _clear_auth_env(monkeypatch)
    monkeypatch.setenv("AUTH_ENABLED", "true")
    monkeypatch.setenv("AUTH_HS256_SECRET", "env-secret-123")

    settings = get_auth_settings()

    assert isinstance(settings, AuthSettings)
    assert settings.enabled is True
    assert settings.hs256_secret == "env-secret-123"  # noqa: S105


@pytest.mark.usefixtures("_auth_env_isolated")
def test_auth_settings_env_override_disabled(monkeypatch: pytest.MonkeyPatch) -> None:
    """AUTH_ENABLED=0 yields disabled and secret can be absent."""
    _clear_auth_env(monkeypatch)
    monkeypatch.setenv("AUTH_ENABLED", "0")

    settings = get_auth_settings()

    assert settings.enabled is False
    # When disabled, we don't care about secret, but env-driven path keeps value as-is.
    assert settings.hs256_secret is None or isinstance(settings.hs256_secret, str)


@pytest.mark.usefixtures("_auth_env_isolated")
def test_auth_settings_fallback_to_application_settings(monkeypatch: pytest.MonkeyPatch) -> None:
    """Without AUTH_ENABLED env, we fall back to the real application Settings."""
    _clear_auth_env(monkeypatch)

    # What the application actually thinks the auth config is:
    app_settings = get_app_settings()

    settings = get_auth_settings()

    assert isinstance(settings, AuthSettings)
    assert settings.enabled is app_settings.auth_enabled
    assert settings.hs256_secret == app_settings.auth_hs256_secret


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def _auth_env_isolated(monkeypatch: pytest.MonkeyPatch) -> None:
    """Ensure AUTH_* env is cleaned up between tests to avoid cross-test bleed."""
    original_enabled = os.getenv("AUTH_ENABLED")
    original_secret = os.getenv("AUTH_HS256_SECRET")

    yield

    # restore
    if original_enabled is not None:
        monkeypatch.setenv("AUTH_ENABLED", original_enabled)
    else:
        monkeypatch.delenv("AUTH_ENABLED", raising=False)

    if original_secret is not None:
        monkeypatch.setenv("AUTH_HS256_SECRET", original_secret)
    else:
        monkeypatch.delenv("AUTH_HS256_SECRET", raising=False)
