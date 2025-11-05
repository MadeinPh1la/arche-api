# src/stacklion_api/infrastructure/observability/metrics_market_data.py
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

from prometheus_client import Counter, Histogram

# ---------------------------------------------------------------------------
# Core metrics (names are part of the public contract for tests / dashboards)
# ---------------------------------------------------------------------------

market_data_gateway_latency_seconds = Histogram(
    "stacklion_market_data_gateway_latency_seconds",
    "Latency seconds for upstream market data provider requests",
    labelnames=("provider", "endpoint", "interval"),
    buckets=(0.01, 0.025, 0.05, 0.1, 0.25, 0.5, 1, 2.5, 5, 10, 30),
)

market_data_errors_total = Counter(
    "stacklion_market_data_errors_total",
    "Total market data errors by reason and route",
    labelnames=("reason", "route"),
)

market_data_cache_hits_total = Counter(
    "stacklion_market_data_cache_hits_total",
    "Cache hit count for market data lookups",
    labelnames=("use_case",),
)
market_data_cache_misses_total = Counter(
    "stacklion_market_data_cache_misses_total",
    "Cache miss count for market data lookups",
    labelnames=("use_case",),
)

stacklion_usecase_historical_quotes_latency_seconds = Histogram(
    "stacklion_usecase_historical_quotes_latency_seconds",
    "End-to-end latency seconds for the historical quotes use case",
)


# ---------------------------------------------------------------------------
# Helper API
# ---------------------------------------------------------------------------
@dataclass
class _Observation:
    """Mutable observation for a single upstream call.

    Attributes:
        _start_ns: Monotonic start time (ns).
        provider: Upstream provider (e.g., "marketstack").
        endpoint: Provider endpoint (e.g., "eod", "intraday").
        interval: Aggregation interval label ("1d", "1m", etc.).
        _has_error: Whether an error was recorded.
        _error_reason: Stable, machine-readable error reason (optional).
    """

    _start_ns: int
    provider: str
    endpoint: str
    interval: str
    _has_error: bool = False
    _error_reason: str | None = None

    def mark_error(self, *, reason: str) -> None:
        """Mark this observation as an error for metrics purposes.

        Args:
            reason: Stable error label such as "rate_limited", "unavailable",
                "validation", "bad_request".
        """
        self._has_error = True
        self._error_reason = reason


@contextmanager
def observe_upstream_request(
    *, provider: str, endpoint: str, interval: str
) -> Generator[_Observation, None, None]:
    """Observe an upstream provider request for metrics.

    Records a latency bucket in ``stacklion_market_data_gateway_latency_seconds``.
    If ``mark_error(reason=...)`` is called within the context, increments the
    ``stacklion_market_data_errors_total`` counter with the given reason and a
    route label derived from the endpoint.

    Args:
        provider: Provider name (e.g., "marketstack").
        endpoint: Endpoint name (e.g., "eod", "intraday").
        interval: Interval label ("1d", "1m", etc.).

    Yields:
        A mutable observation object with ``mark_error``.
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
        market_data_gateway_latency_seconds.labels(provider, endpoint, interval).observe(elapsed_s)

        if obs._has_error and obs._error_reason:
            market_data_errors_total.labels(
                obs._error_reason, f"/v1/quotes/historical:{endpoint}"
            ).inc()


def inc_market_data_error(reason: str, route: str) -> None:
    """Increment market data error counter with a stable reason/route.

    Args:
        reason: Stable error label (e.g., "rate_limited", "validation").
        route: HTTP route path (e.g., "/v1/quotes/historical").
    """
    market_data_errors_total.labels(reason, route).inc()
