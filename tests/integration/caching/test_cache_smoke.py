import json

import pytest

from stacklion_api.infrastructure.caching.json_cache import RedisJsonCache
from stacklion_api.infrastructure.caching.redis_client import get_redis_client


@pytest.mark.asyncio
async def test_cache_roundtrip():
    cache = RedisJsonCache(namespace="test:v1")
    key = "abc123"
    val = {"hello": "world", "n": 1}
    await cache.set_json(key, val, ttl=60)
    out = await cache.get_json(key)
    assert out == val

    # Verify raw exists with namespace
    redis = get_redis_client()
    assert await redis.get("test:v1:abc123") == json.dumps(val)
