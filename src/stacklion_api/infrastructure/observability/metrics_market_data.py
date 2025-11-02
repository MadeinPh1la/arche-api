# Copyright (c) Stacklion.
# SPDX-License-Identifier: MIT
"""Market Data Observability Metrics.

Prometheus metrics for market-data interactions (success/error counters,
cache hit/miss counters, and latency histograms) plus small helpers to
record labeled observations.

Label model (stable):
    * stacklion_market_data_success_total(provider, interval)
    * stacklion_market_data_errors_total(reason, endpoint)
    * stacklion_market_data_upstream_request_duration_seconds(provider, endpoint, interval, status)
    * stacklion_market_data_gateway_latency_seconds(provider, endpoint, interval)
    * stacklion_market_data_cache_{hits,misses}_total(surface)
    * stacklion_usecase_historical_quotes_latency_seconds(interval, outcome)

This module is framework-agnostic and safe to import anywhere.
"""

from __future__ import annotations

from collections.abc import Generator
from contextlib import contextmanager
from time import monotonic
from typing import Literal

from prometheus_client import Counter, Histogram

# ---------------------------------------------------------------------------
# Counters
# ---------------------------------------------------------------------------

#: Total successful upstream market-data fetches.
market_data_success_total: Counter = Counter(
    "stacklion_market_data_success_total",
    "Total successful upstream market data fetches",
    labelnames=("provider", "interval"),
)

#: Total failed upstream market-data fetches by coarse reason and logical endpoint.
market_data_errors_total: Counter = Counter(
    "stacklion_market_data_errors_total",
    "Total failed upstream market data fetches by reason",
    labelnames=("reason", "endpoint"),
)

#: Cache hit counter for a given logical surface (e.g., 'historical_quotes').
market_data_cache_hits_total: Counter = Counter(
    "stacklion_market_data_cache_hits_total",
    "Total cache hits for market data surfaces",
    labelnames=("surface",),
)

#: Cache miss counter for a given logical surface.
market_data_cache_misses_total: Counter = Counter(
    "stacklion_market_data_cache_misses_total",
    "Total cache misses for market data surfaces",
    labelnames=("surface",),
)

# ---------------------------------------------------------------------------
# Histograms
# ---------------------------------------------------------------------------

#: Upstream request latency in seconds with coarse status classification.
upstream_request_duration_seconds: Histogram = Histogram(
    "stacklion_market_data_upstream_request_duration_seconds",
    "Latency of upstream market data requests (seconds)",
    labelnames=("provider", "endpoint", "interval", "status"),
    buckets=(0.05, 0.1, 0.25, 0.5, 1.0, 2.5, 5.0, 10.0),
)

#: Back-compat histogram for gateway-level latency (used by tests).
stacklion_market_data_gateway_latency_seconds: Histogram = Histogram(
    "stacklion_market_data_gateway_latency_seconds",
    "Latency of market data gateway calls (seconds)",
    labelnames=("provider", "endpoint", "interval"),
    buckets=(0.05, 0.1, 0.25, 0.5, 1.0, 2.5, 5.0, 10.0),
)

#: Use-case latency for Historical Quotes.
stacklion_usecase_historical_quotes_latency_seconds: Histogram = Histogram(
    "stacklion_usecase_historical_quotes_latency_seconds",
    "Latency of GetHistoricalQuotesUseCase.execute (seconds)",
    labelnames=("interval", "outcome"),
    buckets=(0.01, 0.025, 0.05, 0.1, 0.25, 0.5, 1.0, 2.5, 5.0, 10.0),
)

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

StatusLabel = Literal["success", "error"]


def inc_market_data_error(reason: str, endpoint: str) -> None:
    """Increment the labeled market-data error counter.

    Args:
        reason: Coarse error cause (e.g., ``"rate_limited"``, ``"validation"``,
            ``"bad_request"``, ``"unavailable"``, ``"quota_exceeded"``,
            ``"not_found"``).
        endpoint: Logical endpoint name (e.g., ``"eod"``, ``"intraday"``,
            ``"latest"``, or a public surface like ``"/v1/quotes/historical"``).

    Returns:
        None
    """
    market_data_errors_total.labels(reason=reason, endpoint=endpoint).inc()


class _Observation:
    """Mutable observation captured by :func:`observe_upstream_request`.

    Attributes:
        status: Outcome label to record on exit. Defaults to ``"success"`` and
            should be set to ``"error"`` by the caller when appropriate.
    """

    __slots__ = ("status",)

    def __init__(self) -> None:
        self.status: StatusLabel = "success"


@contextmanager
def observe_upstream_request(
    *,
    provider: str,
    endpoint: str,
    interval: str,
) -> Generator[_Observation, None, None]:
    """Observe latency for an upstream request.

    Yields a mutable observation whose ``status`` can be flipped by the caller.
    If an exception escapes the context, ``status`` is recorded as ``"error"``.

    Args:
        provider: External provider label (e.g., ``"marketstack"``).
        endpoint: Provider resource (e.g., ``"eod"``, ``"intraday"``, ``"latest"``).
        interval: Bar interval (e.g., ``"1d"``, ``"1m"``) or ``"latest"``.

    Yields:
        _Observation: An observation handle with a ``status`` attribute.

    Raises:
        Exception: Any exception from the body is propagated after recording
            an ``"error"`` observation.

    Example:
        >>> with observe_upstream_request(provider="marketstack", endpoint="eod", interval="1d") as obs:
        ...     # perform HTTP call
        ...     obs.status = "success"
    """
    start = monotonic()
    obs = _Observation()
    try:
        yield obs
    except Exception:
        obs.status = "error"
        raise
    finally:
        upstream_request_duration_seconds.labels(provider, endpoint, interval, obs.status).observe(
            monotonic() - start
        )


__all__ = [
    "market_data_success_total",
    "market_data_errors_total",
    "market_data_cache_hits_total",
    "market_data_cache_misses_total",
    "upstream_request_duration_seconds",
    "stacklion_market_data_gateway_latency_seconds",
    "stacklion_usecase_historical_quotes_latency_seconds",
    "observe_upstream_request",
    "inc_market_data_error",
]
