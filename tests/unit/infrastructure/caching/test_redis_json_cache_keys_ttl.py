# tests/unit/infrastructure/caching/test_redis_json_cache_keys_ttl.py
from __future__ import annotations

import json

import fakeredis.aioredis
import pytest

from stacklion_api.infrastructure.caching import redis_client as redis_client_module
from stacklion_api.infrastructure.caching.json_cache import TTL_INTRADAY_RECENT_S, RedisJsonCache


@pytest.mark.asyncio
async def test_redis_json_cache_key_shape_and_ttl(monkeypatch):
    """Ensure RedisJsonCache builds full keys and applies TTL."""
    fake = fakeredis.aioredis.FakeRedis(decode_responses=True)
    # Wire the fake into the global Redis client used by the cache.
    monkeypatch.setattr(redis_client_module, "_client", fake)

    cache = RedisJsonCache(namespace="stacklion:market_data:v1")
    tail = "historical:AAPL:1min:2025-01-01T00:00:00+00:00:2025-01-01T01:00:00+00:00:p1:s50"
    payload = {"x": 1}

    await cache.set_json(tail, payload, ttl=TTL_INTRADAY_RECENT_S)

    full_key = f"stacklion:market_data:v1:{tail}"
    assert await fake.get(full_key) == json.dumps(payload)

    ttl = await fake.ttl(full_key)
    # TTL should be positive and not exceed the configured band by much.
    assert ttl > 0
    assert ttl <= TTL_INTRADAY_RECENT_S
