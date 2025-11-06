# Copyright (c) Stacklion.
# SPDX-License-Identifier: MIT
"""Prometheus metrics (lazy/idempotent).

Summary:
    Centralizes Prometheus instruments with *on-demand* creation to avoid
    duplicate registration on re-imports, hot reloads, and test cold-starts.

Design:
    * No registration at import time.
    * Each getter creates the collector once (singleton) and returns it.
    * Keep labels low-cardinality; use bounded buckets for short probes.

Exposed getters:
    - get_readyz_db_latency_seconds()
    - get_readyz_redis_latency_seconds()
"""

from __future__ import annotations

from prometheus_client import REGISTRY, CollectorRegistry, Histogram

# ---------------------------------------------------------------------
# internal singletons (created on first use, then reused)
# ---------------------------------------------------------------------
_readyz_db_latency: Histogram | None = None
_readyz_redis_latency: Histogram | None = None


def _registry() -> CollectorRegistry:
    """Return the active registry (tests can monkeypatch prometheus_client.REGISTRY)."""
    return REGISTRY


def get_readyz_db_latency_seconds() -> Histogram:
    """Idempotently return the Postgres readiness probe latency histogram."""
    global _readyz_db_latency
    if _readyz_db_latency is None:
        _readyz_db_latency = Histogram(
            name="readyz_db_latency_seconds",
            documentation="Latency of Postgres readiness probe (seconds).",
            buckets=(0.01, 0.025, 0.05, 0.1, 0.25, 0.5, 1.0, 2.5, 5.0),
            registry=_registry(),
        )
    return _readyz_db_latency


def get_readyz_redis_latency_seconds() -> Histogram:
    """Idempotently return the Redis readiness probe latency histogram."""
    global _readyz_redis_latency
    if _readyz_redis_latency is None:
        _readyz_redis_latency = Histogram(
            name="readyz_redis_latency_seconds",
            documentation="Latency of Redis readiness probe (seconds).",
            buckets=(0.005, 0.01, 0.025, 0.05, 0.1, 0.25, 0.5, 1.0),
            registry=_registry(),
        )
    return _readyz_redis_latency


__all__ = [
    "get_readyz_db_latency_seconds",
    "get_readyz_redis_latency_seconds",
]
