# tests/unit/infrastructure/caching/test_redis_json_cache_singleflight.py
from __future__ import annotations

import asyncio

import fakeredis.aioredis
import pytest

from stacklion_api.infrastructure.caching import redis_client as redis_client_module
from stacklion_api.infrastructure.caching.json_cache import TTL_QUOTE_HOT_S, RedisJsonCache


@pytest.mark.asyncio
async def test_singleflight_loader_invoked_once_under_concurrency(monkeypatch):
    """Concurrent callers for the same key should only invoke the loader once."""
    fake = fakeredis.aioredis.FakeRedis(decode_responses=True)
    monkeypatch.setattr(redis_client_module, "_client", fake)

    cache = RedisJsonCache(namespace="stacklion:market_data:v1")

    key = "quote:AAPL"
    loader_calls = 0

    async def loader():
        nonlocal loader_calls
        loader_calls += 1
        await asyncio.sleep(0.01)
        return {"ticker": "AAPL", "price": "123.45"}

    async def worker():
        return await cache.get_or_set_json_singleflight(
            key,
            ttl=TTL_QUOTE_HOT_S,
            loader=loader,
            lock_ttl=1,
            wait_timeout=0.5,
            wait_interval=0.005,
        )

    # Launch a small swarm of concurrent requests.
    results = await asyncio.gather(*(worker() for _ in range(5)))
    assert all(r is not None for r in results)
    assert loader_calls == 1
