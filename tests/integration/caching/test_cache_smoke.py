# tests/integration/caching/test_cache_smoke.py
import json

import pytest

from stacklion_api.infrastructure.caching.json_cache import RedisJsonCache
from stacklion_api.infrastructure.caching.redis_client import get_redis_client
from stacklion_api.infrastructure.observability.metrics import (
    get_cache_operation_duration_seconds,
    get_cache_operations_total,
)


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

    # Verify cache metrics were recorded with expected labels.
    ops_counter = get_cache_operations_total()
    duration_hist = get_cache_operation_duration_seconds()

    seen_ops: set[tuple[str | None, str | None, str | None]] = set()
    for metric in ops_counter.collect():
        for sample in metric.samples:
            if sample.name == "cache_operations_total":
                seen_ops.add(
                    (
                        sample.labels.get("operation"),
                        sample.labels.get("namespace"),
                        sample.labels.get("hit"),
                    )
                )

    assert ("set_json", "test:v1", "n/a") in seen_ops
    assert ("get_json", "test:v1", "true") in seen_ops

    # Sanity check that duration histogram has at least one sample for this namespace.
    seen_hist_ops: set[str] = set()
    for metric in duration_hist.collect():
        for sample in metric.samples:
            op = sample.labels.get("operation")
            ns = sample.labels.get("namespace")
            if ns == "test:v1" and op:
                seen_hist_ops.add(op)

    assert "set_json" in seen_hist_ops
    assert "get_json" in seen_hist_ops
