# tests/unit/dependencies/test_bootstrap_error_paths.py
from __future__ import annotations

import pytest
from fastapi import FastAPI

from arche_api.dependencies.core.bootstrap import bootstrap


@pytest.mark.asyncio
async def test_bootstrap_cleans_up_on_errors(monkeypatch: pytest.MonkeyPatch):
    """Exercise the error-handling branches in bootstrap's finally block."""
    app = FastAPI()

    # Patch out engine/redis init so they don't touch real infrastructure.
    import arche_api.infrastructure.caching.redis_client as redis_client
    import arche_api.infrastructure.database.session as db_session

    monkeypatch.setattr(db_session, "init_engine_and_sessionmaker", lambda s: None, raising=True)
    monkeypatch.setattr(redis_client, "init_redis", lambda s: None, raising=True)

    # Track calls and simulate failures on shutdown.
    closed = {"http": False, "redis": False, "db": False}

    async def _fake_aclose(*args, **kwargs):
        closed["http"] = True
        raise RuntimeError("boom-http")

    async def _fake_close_redis():
        closed["redis"] = True
        raise RuntimeError("boom-redis")

    async def _fake_dispose():
        closed["db"] = True
        raise RuntimeError("boom-db")

    monkeypatch.setattr(redis_client, "close_redis", _fake_close_redis, raising=True)
    monkeypatch.setattr(db_session, "dispose_engine", _fake_dispose, raising=True)

    async with bootstrap(app) as state:
        # Patch http_client after it's created (instance-level)
        monkeypatch.setattr(state.http_client, "aclose", _fake_aclose, raising=False)

    # All cleanup paths should have been exercised without raising out of the context manager.
    assert closed["http"] is True
    assert closed["redis"] is True
    assert closed["db"] is True
