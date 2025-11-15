from __future__ import annotations

import pytest

from stacklion_api.infrastructure.external_apis.marketstack.settings import (
    MarketstackSettings,
    _default_allowed_intervals,
)


def test_default_allowed_intervals() -> None:
    intervals = _default_allowed_intervals()
    assert intervals == ["1h", "30min", "15min"]


def test_marketstack_settings_defaults(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("MARKETSTACK_ACCESS_KEY", "dummy-key")

    settings = MarketstackSettings()

    assert settings.base_url == "https://api.marketstack.com/v2"
    assert settings.access_key.get_secret_value() == "dummy-key"
    assert settings.timeout_s == 8.0
    assert settings.max_retries == 4
    assert settings.allowed_intraday_intervals == ["1h", "30min", "15min"]


def test_marketstack_settings_env_overrides(monkeypatch: pytest.MonkeyPatch) -> None:
    """Environment variables override defaults and raw intervals are normalized."""
    monkeypatch.setenv("MARKETSTACK_ACCESS_KEY", "env-key")
    monkeypatch.setenv("MARKETSTACK_BASE_URL", "https://example.test/v2")
    monkeypatch.setenv("MARKETSTACK_TIMEOUT_S", "3.5")
    monkeypatch.setenv("MARKETSTACK_MAX_RETRIES", "7")
    # NOTE: field name is allowed_intraday_intervals_raw → env var ends with _RAW
    monkeypatch.setenv(
        "MARKETSTACK_ALLOWED_INTRADAY_INTERVALS_RAW",
        " 1M , 5Min, ,15MIN ",
    )

    settings = MarketstackSettings()

    assert settings.access_key.get_secret_value() == "env-key"
    assert settings.base_url == "https://example.test/v2"
    assert settings.timeout_s == 3.5
    assert settings.max_retries == 7
    assert settings.allowed_intraday_intervals == ["1m", "5min", "15min"]


def test_marketstack_settings_ignores_unknown_env(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("MARKETSTACK_ACCESS_KEY", "key")
    monkeypatch.setenv("MARKETSTACK_SOME_UNUSED_FLAG", "1")

    settings = MarketstackSettings()

    assert settings.access_key.get_secret_value() == "key"
    assert not hasattr(settings, "some_unused_flag")
