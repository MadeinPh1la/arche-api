"""Prometheus metric definitions used across the application.

This module centralizes metric instruments (e.g., histograms, counters)
to avoid scattered definitions and to keep label/bucket policies consistent.

Design:
    * Keep labels low-cardinality.
    * Prefer bounded histogram buckets for short operations like probes.
    * Definitions only (no registration logic needed for the default registry).

Exposed metrics:
    * READYZ_DB_LATENCY: Postgres readiness probe latency (seconds).
    * READYZ_REDIS_LATENCY: Redis readiness probe latency (seconds).
"""

from __future__ import annotations

from prometheus_client import Histogram

# Buckets tuned for sub-second to a few seconds. Avoid excessive cardinality.
READYZ_DB_LATENCY: Histogram = Histogram(
    name="readyz_db_latency_seconds",
    documentation="Latency of Postgres readiness probe (seconds).",
    buckets=(0.01, 0.025, 0.05, 0.1, 0.25, 0.5, 1.0, 2.5, 5.0),
)

READYZ_REDIS_LATENCY: Histogram = Histogram(
    name="readyz_redis_latency_seconds",
    documentation="Latency of Redis readiness probe (seconds).",
    buckets=(0.005, 0.01, 0.025, 0.05, 0.1, 0.25, 0.5, 1.0),
)
