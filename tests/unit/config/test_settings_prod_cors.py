import os
from contextlib import contextmanager

import pytest

from stacklion_api.config.settings import get_settings


def _req_env(**over):
    base = {
        "ENVIRONMENT": "production",
        "DATABASE_URL": "postgresql+asyncpg://stacklion:stacklion@localhost:5432/stacklion_test",
        "REDIS_URL": "redis://localhost:6379/0",
        "CLERK_ISSUER": "https://example.clerk.accounts.dev",
    }
    base.update(over)
    return base


@contextmanager
def _with_env(env: dict[str, str]):
    old = {k: os.environ.get(k) for k in env}
    try:
        os.environ.update(env)
        # clear the lru cache so settings re-reads env
        get_settings.cache_clear()  # type: ignore[attr-defined]
        yield
    finally:
        for k, v in old.items():
            if v is None:
                os.environ.pop(k, None)
            else:
                os.environ[k] = v
        get_settings.cache_clear()  # type: ignore[attr-defined]


def test_production_rejects_wildcard_cors():
    env = _req_env(ALLOWED_ORIGINS="*")
    with _with_env(env), pytest.raises(RuntimeError):
        _ = get_settings()
