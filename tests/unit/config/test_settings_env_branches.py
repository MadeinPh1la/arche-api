import os
from contextlib import contextmanager

from stacklion_api.config.settings import get_settings


@contextmanager
def _env(**pairs: str | None):
    old = {k: os.environ.get(k) for k in pairs}
    try:
        for k, v in pairs.items():
            if v is None:
                os.environ.pop(k, None)
            else:
                os.environ[k] = v
        # Ensure get_settings() re-reads env for this block
        get_settings.cache_clear()  # type: ignore[attr-defined]
        yield
    finally:
        for k, v in old.items():
            if v is None:
                os.environ.pop(k, None)
            else:
                os.environ[k] = v
        get_settings.cache_clear()  # reset again


def _required_basics() -> dict[str, str]:
    # Minimal required fields for Settings to validate
    return {
        "DATABASE_URL": "postgresql+asyncpg://stacklion:stacklion@localhost:5432/stacklion_test",
        "REDIS_URL": "redis://localhost:6379/0",
        "CLERK_ISSUER": "https://example.clerk.accounts.dev",
    }


def test_rate_limit_and_allowed_origins_parsing():
    env = {
        **_required_basics(),
        "RATE_LIMIT_ENABLED": "true",
        "ALLOWED_ORIGINS": "https://a.com, https://b.com",
    }
    with _env(**env):
        s = get_settings()
        assert s.rate_limit_enabled is True
        # Settings exposes parsed list as cors_allow_origins
        assert set(s.cors_allow_origins) == {"https://a.com", "https://b.com"}


def test_defaults_when_unset_are_sane():
    env = {**_required_basics()}
    with _env(**env):
        s = get_settings()
        assert isinstance(s.rate_limit_enabled, bool)
        assert isinstance(s.cors_allow_origins, list)
