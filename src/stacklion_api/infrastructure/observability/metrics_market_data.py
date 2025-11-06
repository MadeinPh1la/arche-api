# Copyright (c) Stacklion.
# SPDX-License-Identifier: MIT
"""Market Data observability helpers and Prometheus metrics.

Exports used across the codebase:
    - market_data_gateway_latency_seconds  (Histogram)
    - market_data_errors_total             (Counter)
    - market_data_cache_hits_total         (Counter)
    - market_data_cache_misses_total       (Counter)
    - stacklion_usecase_historical_quotes_latency_seconds (Histogram)
    - observe_upstream_request(...)        (context manager)
    - inc_market_data_error(...)           (helper to increment error counter)

Prometheus metric names (what /metrics exposes and tests scan for):
    * stacklion_market_data_gateway_latency_seconds  (Histogram)
    * stacklion_market_data_errors_total             (Counter)
    * stacklion_market_data_cache_hits_total         (Counter)
    * stacklion_market_data_cache_misses_total       (Counter)
    * stacklion_usecase_historical_quotes_latency_seconds (Histogram)
"""

from __future__ import annotations

import time
from collections.abc import Generator
from contextlib import contextmanager
from dataclasses import dataclass

from prometheus_client import REGISTRY, CollectorRegistry, Counter, Histogram

# Singletons (created on first use, then reused)
_market_data_latency: Histogram | None = None
_market_data_errors: Counter | None = None
_market_data_cache_hits: Counter | None = None
_market_data_cache_misses: Counter | None = None
_usecase_hist_quotes: Histogram | None = None


def _registry() -> CollectorRegistry:
    # Allow tests to inject an alternative registry by monkeypatching REGISTRY
    return REGISTRY


def get_market_data_gateway_latency_seconds() -> Histogram:
    """Idempotently return the upstream latency histogram."""
    global _market_data_latency
    if _market_data_latency is None:
        _market_data_latency = Histogram(
            "stacklion_market_data_gateway_latency_seconds",
            "Latency seconds for upstream market data provider requests",
            labelnames=("provider", "endpoint", "interval"),
            buckets=(0.01, 0.025, 0.05, 0.1, 0.25, 0.5, 1, 2.5, 5, 10, 30),
            registry=_registry(),
        )
    return _market_data_latency


def get_market_data_errors_total() -> Counter:
    """Idempotently return the upstream error counter."""
    global _market_data_errors
    if _market_data_errors is None:
        _market_data_errors = Counter(
            "stacklion_market_data_errors_total",
            "Total market data errors by reason and route",
            labelnames=("reason", "route"),
            registry=_registry(),
        )
    return _market_data_errors


def get_market_data_cache_hits_total() -> Counter:
    """Idempotently return cache hit counter."""
    global _market_data_cache_hits
    if _market_data_cache_hits is None:
        _market_data_cache_hits = Counter(
            "stacklion_market_data_cache_hits_total",
            "Cache hit count for market data lookups",
            labelnames=("use_case",),
            registry=_registry(),
        )
    return _market_data_cache_hits


def get_market_data_cache_misses_total() -> Counter:
    """Idempotently return cache miss counter."""
    global _market_data_cache_misses
    if _market_data_cache_misses is None:
        _market_data_cache_misses = Counter(
            "stacklion_market_data_cache_misses_total",
            "Cache miss count for market data lookups",
            labelnames=("use_case",),
            registry=_registry(),
        )
    return _market_data_cache_misses


def get_usecase_historical_quotes_latency_seconds() -> Histogram:
    """Idempotently return the historical quotes use-case histogram."""
    global _usecase_hist_quotes
    if _usecase_hist_quotes is None:
        _usecase_hist_quotes = Histogram(
            "stacklion_usecase_historical_quotes_latency_seconds",
            "End-to-end latency seconds for the historical quotes use case",
            registry=_registry(),
        )
    return _usecase_hist_quotes


# ----------------------------- Helper API --------------------------------- #


@dataclass
class _Observation:
    """Mutable observation for a single upstream call."""

    _start_ns: int
    provider: str
    endpoint: str
    interval: str
    _has_error: bool = False
    _error_reason: str | None = None

    def mark_error(self, *, reason: str) -> None:
        self._has_error = True
        self._error_reason = reason


@contextmanager
def observe_upstream_request(
    *, provider: str, endpoint: str, interval: str
) -> Generator[_Observation, None, None]:
    """Observe an upstream provider request for metrics."""
    obs = _Observation(
        _start_ns=time.monotonic_ns(),
        provider=provider,
        endpoint=endpoint,
        interval=interval,
    )
    try:
        yield obs
    finally:
        elapsed_s = (time.monotonic_ns() - obs._start_ns) / 1e9
        get_market_data_gateway_latency_seconds().labels(provider, endpoint, interval).observe(
            elapsed_s
        )

        if obs._has_error and obs._error_reason:
            get_market_data_errors_total().labels(
                obs._error_reason, f"/v1/quotes/historical:{endpoint}"
            ).inc()


def inc_market_data_error(reason: str, route: str) -> None:
    """Increment market data error counter with a stable reason/route."""
    get_market_data_errors_total().labels(reason, route).inc()


__all__ = [
    "get_market_data_gateway_latency_seconds",
    "get_market_data_errors_total",
    "get_market_data_cache_hits_total",
    "get_market_data_cache_misses_total",
    "get_usecase_historical_quotes_latency_seconds",
    "observe_upstream_request",
    "inc_market_data_error",
]
