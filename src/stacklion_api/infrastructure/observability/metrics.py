# Copyright (c)
# SPDX-License-Identifier: MIT
"""Registry-aware Prometheus histogram factories for health probes.

These helpers return **singleton `Histogram` objects bound to the current
`prometheus_client.REGISTRY`**. They are safe under hot reload and in tests
that replace `prom.REGISTRY` between cases (e.g., cold-start).

Key properties:
    * No duplicate-registration errors (ValueError: Duplicated timeseries).
    * Stable identity within a given registry (subsequent calls reuse the same
      `Histogram` object).
    * Automatic cache reset when the active registry changes.
    * Explicit buckets so `_bucket/_count/_sum` appear after the first observe.

Example:
    db_hist = get_readyz_db_latency_seconds()
    # ... run your DB probe within an async function and compute duration ...
    db_hist.observe(0.012)  # seconds
"""

from __future__ import annotations

import logging
import threading
from contextlib import suppress

import prometheus_client as prom
from prometheus_client import Histogram

_log = logging.getLogger(__name__)

# Explicit histogram buckets (seconds) for API latencies.
_BUCKETS: tuple[float, ...] = (0.005, 0.01, 0.025, 0.05, 0.1, 0.25, 0.5, 1.0, 2.5, 5.0, 10.0)

# Cache per active registry identity.
_registry_id: int | None = None
_hist_cache: dict[str, Histogram] = {}
_lock = threading.RLock()


def _active_registry_id() -> int:
    return id(prom.REGISTRY)


def _ensure_registry() -> None:
    """Ensure the cache aligns with the active default registry; reset on change."""
    global _registry_id
    with _lock:
        rid = _active_registry_id()
        if _registry_id is None or _registry_id != rid:
            _hist_cache.clear()
            _registry_id = rid


def _lookup_existing(name: str) -> Histogram | None:
    """Return an already-registered Histogram from the active registry, if any.

    We consult `prom.REGISTRY._names_to_collectors` (internal to the reference
    implementation). If present and of the expected type, reuse it.
    """
    with _lock, suppress(Exception):
        mapping = getattr(prom.REGISTRY, "_names_to_collectors", None)
        if isinstance(mapping, dict):
            col = mapping.get(name)
            if isinstance(col, Histogram):
                return col
    return None


def _get_or_create_hist(name: str, help_text: str) -> Histogram:
    """Get or create a registry-bound histogram with stable identity.

    Strategy:
        1) Return from the module cache if present for the active registry.
        2) If the registry already has a collector by this name, reuse it.
        3) Otherwise create & register a new histogram.
        4) If registration races and raises `Duplicated timeseries`, retry (2).

    Args:
        name: Metric name, e.g. "readyz_db_latency_seconds".
        help_text: Human-readable description.

    Returns:
        Histogram: Bound to the current `prom.REGISTRY`.
    """
    with _lock:
        # 1) cache hit
        hit = _hist_cache.get(name)
        if isinstance(hit, Histogram):
            return hit

        # 2) registry already holds it?
        existing = _lookup_existing(name)
        if isinstance(existing, Histogram):
            _hist_cache[name] = existing
            return existing

        # 3) create + register
        try:
            h = Histogram(name, help_text, buckets=_BUCKETS, registry=prom.REGISTRY)
            _hist_cache[name] = h
            return h
        except ValueError as exc:
            # 4) concurrent registration; reuse the one that won the race
            if "Duplicated timeseries" in str(exc):
                again = _lookup_existing(name)
                if isinstance(again, Histogram):
                    _hist_cache[name] = again
                    return again
            _log.exception("Failed to register Prometheus histogram %s", name)
            raise


def get_readyz_db_latency_seconds() -> Histogram:
    """Return (and cache) the DB readiness latency histogram.

    Returns:
        Histogram: Bound to the current `prom.REGISTRY`.
    """
    _ensure_registry()
    return _get_or_create_hist(
        name="readyz_db_latency_seconds",
        help_text="Latency of Postgres readiness probe (seconds).",
    )


def get_readyz_redis_latency_seconds() -> Histogram:
    """Return (and cache) the Redis readiness latency histogram.

    Returns:
        Histogram: Bound to the current `prom.REGISTRY`.
    """
    _ensure_registry()
    return _get_or_create_hist(
        name="readyz_redis_latency_seconds",
        help_text="Latency of Redis readiness probe (seconds).",
    )
