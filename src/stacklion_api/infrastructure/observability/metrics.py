# Copyright (c)
# SPDX-License-Identifier: MIT
"""Prometheus metrics utilities (registry-aware, hot-reload safe).

This module provides two categories of metrics helpers:

1) **Health-probe histograms with stable identity**
   Functions like :func:`get_readyz_db_latency_seconds` return a *singleton*
   ``Histogram`` bound to the **current** ``prometheus_client.REGISTRY``.
   - Safe under hot reload and tests that swap the default registry.
   - No duplicate-registration errors.
   - Cache automatically resets when the active registry changes.

2) **Operational ingest metrics (factory accessors)**
   The ingest metrics (latency, rows, errors, data lag) are also provided
   through accessor functions, ensuring registry safety in tests and dev.

All histograms use explicit buckets so ``_bucket/_count/_sum`` series appear
after the first ``observe(...)`` call.

Design notes:
- We *intentionally* reuse the default registry (``prom.REGISTRY``) to be
  compatible with Prometheus’ default exposition middleware. For test isolation,
  swap the registry and call the accessors again.
- Labelled metrics are created exactly once per registry. Callers should
  immediately ``.labels(...).observe/inc`` as usual.

Example:
    db_hist = get_readyz_db_latency_seconds()
    db_hist.observe(0.012)

    ingest = get_ingest_latency_seconds()
    ingest.labels(source="marketstack", endpoint="intraday").observe(0.250)
"""

from __future__ import annotations

import logging
import threading
from contextlib import suppress
from typing import Final

import prometheus_client as prom
from prometheus_client import Counter, Histogram

from .metrics_market_data import (
    observe_upstream_request as observe_market_data_request,
)

_log = logging.getLogger(__name__)

# Backwards-compatible alias: anything importing observe_upstream_request from
# this module will use the market-data-specific one.
observe_upstream_request = observe_market_data_request

# ---------------------------------------------------------------------------
# Common histogram buckets (seconds)
_BUCKETS: Final[tuple[float, ...]] = (
    0.005,
    0.010,
    0.025,
    0.050,
    0.100,
    0.250,
    0.500,
    1.000,
    2.500,
    5.000,
    10.000,
)

# Cache keyed by metric name within the currently-active registry.
_registry_id: int | None = None
_hist_cache: dict[str, Histogram] = {}
_counter_cache: dict[str, Counter] = {}
_lock = threading.RLock()


# ---------------------------------------------------------------------------
# Registry-handling primitives


def _active_registry_id() -> int:
    """Return an identifier for the current default registry.

    Returns:
        int: Identity of the active ``prom.REGISTRY`` object.
    """
    return id(prom.REGISTRY)


def _ensure_registry() -> None:
    """Reset caches if the active registry changed.

    This must be called before any metric lookup/creation to avoid mixing
    collectors across registries (common in tests).
    """
    global _registry_id
    with _lock:
        rid = _active_registry_id()
        if _registry_id is None or _registry_id != rid:
            _hist_cache.clear()
            _counter_cache.clear()
            _registry_id = rid


def _lookup_existing_hist(name: str) -> Histogram | None:
    """Return a previously-registered ``Histogram`` from the active registry.

    Args:
        name: Collector name.

    Returns:
        Histogram | None: Existing collector if present and of the correct type.
    """
    with _lock, suppress(Exception):
        mapping = getattr(prom.REGISTRY, "_names_to_collectors", None)
        if isinstance(mapping, dict):
            col = mapping.get(name)
            if isinstance(col, Histogram):
                return col
    return None


def _lookup_existing_counter(name: str) -> Counter | None:
    """Return a previously-registered ``Counter`` from the active registry.

    Args:
        name: Collector name.

    Returns:
        Counter | None: Existing collector if present and of the correct type.
    """
    with _lock, suppress(Exception):
        mapping = getattr(prom.REGISTRY, "_names_to_collectors", None)
        if isinstance(mapping, dict):
            col = mapping.get(name)
            if isinstance(col, Counter):
                return col
    return None


# ---------------------------------------------------------------------------
# Get-or-create helpers


def _get_or_create_hist(
    name: str,
    help_text: str,
    *,
    buckets: tuple[float, ...] = _BUCKETS,
    labelnames: tuple[str, ...] = (),
) -> Histogram:
    """Get or create a registry-bound ``Histogram`` with stable identity.

    Implements the following strategy:
    1. Return from module cache if present for the active registry.
    2. If registry already has a collector by this name, reuse it.
    3. Otherwise, register a new collector on the active registry.
    4. If concurrent registration triggers a duplication error, retry step 2.

    Args:
        name: Metric name (snake_case).
        help_text: Human-readable description.
        buckets: Histogram buckets in seconds.
        labelnames: Optional label names tuple.

    Returns:
        Histogram: Bound to ``prom.REGISTRY``.
    """
    _ensure_registry()
    with _lock:
        cached = _hist_cache.get(name)
        if isinstance(cached, Histogram):
            return cached

        existing = _lookup_existing_hist(name)
        if isinstance(existing, Histogram):
            _hist_cache[name] = existing
            return existing

        # Always pass an iterable of label names; never None (for mypy + stubs).
        labels: tuple[str, ...] = labelnames or ()

        try:
            h = Histogram(
                name,
                help_text,
                labels,
                buckets=buckets,
                registry=prom.REGISTRY,
            )
            _hist_cache[name] = h
            return h
        except ValueError as exc:
            # Duplicated timeseries—another thread/process registered it first.
            if "Duplicated timeseries" in str(exc):
                again = _lookup_existing_hist(name)
                if isinstance(again, Histogram):
                    _hist_cache[name] = again
                    return again
            _log.exception("Failed to register Prometheus histogram %s", name)
            raise


def _get_or_create_counter(
    name: str,
    help_text: str,
    *,
    labelnames: tuple[str, ...] = (),
) -> Counter:
    """Get or create a registry-bound ``Counter`` with stable identity.

    Args:
        name: Metric name (snake_case).
        help_text: Human-readable description.
        labelnames: Optional label names tuple.

    Returns:
        Counter: Bound to ``prom.REGISTRY``.
    """
    _ensure_registry()
    with _lock:
        cached = _counter_cache.get(name)
        if isinstance(cached, Counter):
            return cached

        existing = _lookup_existing_counter(name)
        if isinstance(existing, Counter):
            _counter_cache[name] = existing
            return existing

        labels: tuple[str, ...] = labelnames or ()

        try:
            c = Counter(
                name,
                help_text,
                labels,
                registry=prom.REGISTRY,
            )
            _counter_cache[name] = c
            return c
        except ValueError as exc:
            if "Duplicated timeseries" in str(exc):
                again = _lookup_existing_counter(name)
                if isinstance(again, Counter):
                    _counter_cache[name] = again
                    return again
            _log.exception("Failed to register Prometheus counter %s", name)
            raise


# ---------------------------------------------------------------------------
# Health metrics (registry-aware singletons)


def get_readyz_db_latency_seconds() -> Histogram:
    """Return (and cache) the DB readiness latency histogram.

    Returns:
        Histogram: Collector bound to the active registry.
    """
    return _get_or_create_hist(
        name="readyz_db_latency_seconds",
        help_text="Latency of Postgres readiness probe (seconds).",
        buckets=_BUCKETS,
    )


def get_readyz_redis_latency_seconds() -> Histogram:
    """Return (and cache) the Redis readiness latency histogram.

    Returns:
        Histogram: Collector bound to the active registry.
    """
    return _get_or_create_hist(
        name="readyz_redis_latency_seconds",
        help_text="Latency of Redis readiness probe (seconds).",
        buckets=_BUCKETS,
    )


# ---------------------------------------------------------------------------
# Ingest/operations metrics (registry-aware accessors)


def get_ingest_latency_seconds() -> Histogram:
    """Return histogram for ingest latency.

    Labels:
        source: Provider name (e.g., ``marketstack``).
        endpoint: Endpoint identifier (e.g., ``intraday``).

    Returns:
        Histogram: Labelled collector.
    """
    return _get_or_create_hist(
        name="stacklion_ingest_latency_seconds",
        help_text="Latency (seconds) of ingest operations",
        labelnames=("source", "endpoint"),
    )


def get_ingest_rows_total() -> Counter:
    """Return counter for rows processed during ingest.

    Labels:
        source: Provider name.
        endpoint: Endpoint identifier.
        result: One of ``success|noop|error``.

    Returns:
        Counter: Labelled collector.
    """
    return _get_or_create_counter(
        name="stacklion_ingest_rows_total",
        help_text="Rows ingested by operation",
        labelnames=("source", "endpoint", "result"),
    )


def get_ingest_errors_total() -> Counter:
    """Return counter for errors during ingest.

    Labels:
        source: Provider name.
        endpoint: Endpoint identifier.
        reason: Error class or short reason.

    Returns:
        Counter: Labelled collector.
    """
    return _get_or_create_counter(
        name="stacklion_ingest_errors_total",
        help_text="Errors during ingest",
        labelnames=("source", "endpoint", "reason"),
    )


def get_data_lag_seconds() -> Histogram:
    """Return histogram for data freshness lag (seconds) at source.

    Labels:
        source: Provider name.
        endpoint: Endpoint identifier.

    Returns:
        Histogram: Labelled collector.
    """
    return _get_or_create_hist(
        name="stacklion_data_lag_seconds",
        help_text="Data freshness lag in seconds at the source",
        labelnames=("source", "endpoint"),
    )
