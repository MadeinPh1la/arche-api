# Copyright (c) Stacklion.
# SPDX-License-Identifier: MIT
"""Market Data observability helpers and Prometheus metrics (lazy/idempotent).

Summary:
    Centralized, on-demand Prometheus collectors and helper APIs for observing
    upstream market data calls and high-level use-case latencies. No collectors
    are registered at import time; all are created on first use and cached.

Exposed API:
    - get_market_data_gateway_latency_seconds() -> Histogram
    - get_market_data_errors_total() -> Counter
    - get_market_data_cache_hits_total() -> Counter
    - get_market_data_cache_misses_total() -> Counter
    - get_usecase_historical_quotes_latency_seconds() -> Histogram
    - observe_upstream_request(...) -> context manager
    - inc_market_data_error(reason, route) -> None
"""

from __future__ import annotations

import time
from collections.abc import Generator
from contextlib import contextmanager
from dataclasses import dataclass

from prometheus_client import REGISTRY, CollectorRegistry, Counter, Histogram

__all__ = [
    "get_market_data_gateway_latency_seconds",
    "get_market_data_errors_total",
    "get_market_data_cache_hits_total",
    "get_market_data_cache_misses_total",
    "get_usecase_historical_quotes_latency_seconds",
    "observe_upstream_request",
    "inc_market_data_error",
]

# -----------------------------------------------------------------------------
# Lazy, idempotent collectors
# -----------------------------------------------------------------------------
_market_data_latency: Histogram | None = None
_market_data_errors: Counter | None = None
_market_data_cache_hits: Counter | None = None
_market_data_cache_misses: Counter | None = None
_usecase_hist_quotes: Histogram | None = None


def _registry() -> CollectorRegistry:
    """Return the active Prometheus registry (tests may monkeypatch REGISTRY)."""
    return REGISTRY


def get_market_data_gateway_latency_seconds() -> Histogram:
    """Latency of outbound calls to the market data gateway.

    Labels:
        provider: Upstream provider (e.g., "marketstack").
        endpoint: Provider endpoint ("eod", "intraday", ...).
        interval: Aggregation interval label ("1d", "1m", ...).
    """
    global _market_data_latency
    if _market_data_latency is None:
        _market_data_latency = Histogram(
            "stacklion_market_data_gateway_latency_seconds",
            "Latency seconds for upstream market data provider requests",
            labelnames=("provider", "endpoint", "interval"),
            buckets=(0.01, 0.025, 0.05, 0.1, 0.25, 0.5, 1.0, 2.5, 5.0, 10.0, 30.0),
            registry=_registry(),
        )
    return _market_data_latency


def get_market_data_errors_total() -> Counter:
    """Total market-data errors by (reason, route)."""
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
    """Cache hit counter for market data lookups."""
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
    """Cache miss counter for market data lookups."""
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
    """End-to-end latency for the historical quotes use case."""
    global _usecase_hist_quotes
    if _usecase_hist_quotes is None:
        _usecase_hist_quotes = Histogram(
            "stacklion_usecase_historical_quotes_latency_seconds",
            "End-to-end latency seconds for the historical quotes use case",
            registry=_registry(),
        )
    return _usecase_hist_quotes


# -----------------------------------------------------------------------------
# Helper API
# -----------------------------------------------------------------------------
@dataclass
class _Observation:
    """Mutable observation context for a single upstream call."""

    _start_ns: int
    provider: str
    endpoint: str
    interval: str
    _has_error: bool = False
    _error_reason: str | None = None

    def mark_error(self, *, reason: str) -> None:
        """Mark the observation as an error with a stable reason label."""
        self._has_error = True
        self._error_reason = reason


@contextmanager
def observe_upstream_request(
    *, provider: str, endpoint: str, interval: str
) -> Generator[_Observation, None, None]:
    """Context manager to observe an upstream request.

    Records a latency sample to the gateway histogram and increments the error
    counter if `mark_error()` is called with a reason.

    Args:
        provider: Upstream provider identifier (e.g., "marketstack").
        endpoint: Provider endpoint ("eod", "intraday", ...).
        interval: Aggregation interval label ("1d", "1m", ...).

    Yields:
        _Observation: Mutable object that allows `mark_error(reason=...)`.
    """
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
        get_market_data_gateway_latency_seconds().labels(
            obs.provider, obs.endpoint, obs.interval
        ).observe(elapsed_s)

        if obs._has_error and obs._error_reason:
            get_market_data_errors_total().labels(
                obs._error_reason, f"/v1/quotes/historical:{obs.endpoint}"
            ).inc()


def inc_market_data_error(reason: str, route: str) -> None:
    """Increment the market-data error counter with a stable reason/route."""
    get_market_data_errors_total().labels(reason, route).inc()
