# src/stacklion_api/infrastructure/observability/metrics_market_data.py
# Copyright (c)
# SPDX-License-Identifier: MIT
"""Market Data observability helpers and Prometheus metrics.

This module centralizes all Prometheus metrics related to external market-data
providers (e.g., Marketstack) and the historical quotes use case.

Exports
-------
Core collectors (names are part of the public contract and must remain stable):

* ``stacklion_market_data_gateway_latency_seconds`` (Histogram)
* ``stacklion_market_data_errors_total`` (Counter)
* ``stacklion_market_data_cache_hits_total`` (Counter)
* ``stacklion_market_data_cache_misses_total`` (Counter)
* ``stacklion_usecase_historical_quotes_latency_seconds`` (Histogram)
* ``stacklion_market_data_304_total`` (Counter)
* ``stacklion_market_data_breaker_events_total`` (Counter)
* ``stacklion_market_data_http_status_total`` (Counter)
* ``stacklion_market_data_response_bytes`` (Histogram)
* ``stacklion_market_data_retries_total`` (Counter)

Helpers:

* :func:`observe_upstream_request` – context manager for one upstream call.
* Legacy accessors: ``get_*`` functions returning the underlying collector.
* :func:`inc_market_data_error` – backwards-compatible error counter helper.

Design
------
All collectors are created against the *current* default registry
(:data:`prometheus_client.REGISTRY`) and are safe under:

* tests that swap out ``prom.REGISTRY`` (cold-start and OTEL boot tests),
* module re-imports, and
* concurrent registrations.

If a collector with the same name already exists in the active registry, the
existing instance is reused instead of registering a duplicate.
"""

from __future__ import annotations

from collections.abc import Generator, Sequence
from contextlib import contextmanager, suppress
from dataclasses import dataclass, field
from time import perf_counter
from typing import Any

import prometheus_client as prom
from prometheus_client import Counter, Histogram
from prometheus_client.registry import CollectorRegistry


def _get_or_create_histogram(
    name: str,
    doc: str,
    labelnames: Sequence[str] | None = None,
) -> Histogram:
    """Return a histogram bound to the current default registry.

    This helper is idempotent per active registry:

    1. Look up an existing collector with the given name in the current
       :data:`prom.REGISTRY` and reuse it if it is a :class:`Histogram`.
    2. Otherwise, attempt to register a new histogram on the same registry.
    3. If a concurrent registration caused a ``Duplicated timeseries`` error,
       look up the collector again and reuse it.

    Args:
        name: Metric name (e.g. ``"stacklion_market_data_gateway_latency_seconds"``).
        doc: Human-readable metric description.
        labelnames: Optional iterable of label names.

    Returns:
        A :class:`Histogram` bound to the current :data:`prom.REGISTRY`.
    """
    registry: CollectorRegistry = prom.REGISTRY
    mapping = getattr(
        registry, "_names_to_collectors", {}
    )  # internal but stable in prometheus_client
    existing = mapping.get(name)
    if isinstance(existing, Histogram):
        return existing

    labels = tuple(labelnames) if labelnames is not None else ()
    try:
        return Histogram(name, doc, labels, registry=registry)
    except ValueError as exc:
        # Handle concurrent or prior registration gracefully.
        if "Duplicated timeseries" in str(exc):
            mapping = getattr(registry, "_names_to_collectors", {})
            again = mapping.get(name)
            if isinstance(again, Histogram):
                return again
        raise


def _get_or_create_counter(
    name: str,
    doc: str,
    labelnames: Sequence[str] | None = None,
) -> Counter:
    """Return a counter bound to the current default registry.

    The behavior mirrors :func:`_get_or_create_histogram`, but for
    :class:`Counter` collectors.

    Args:
        name: Metric name.
        doc: Human-readable metric description.
        labelnames: Optional iterable of label names.

    Returns:
        A :class:`Counter` bound to the current :data:`prom.REGISTRY`.
    """
    registry: CollectorRegistry = prom.REGISTRY
    mapping = getattr(registry, "_names_to_collectors", {})
    existing = mapping.get(name)
    if isinstance(existing, Counter):
        return existing

    labels = tuple(labelnames) if labelnames is not None else ()
    try:
        return Counter(name, doc, labels, registry=registry)
    except ValueError as exc:
        if "Duplicated timeseries" in str(exc):
            mapping = getattr(registry, "_names_to_collectors", {})
            again = mapping.get(name)
            if isinstance(again, Counter):
                return again
        raise


# ---------------------------------------------------------------------------
# Core metrics (names are part of the public contract for tests)
# ---------------------------------------------------------------------------

# Gateway latency: tests use observe_upstream_request with provider/endpoint/interval.
market_data_gateway_latency_seconds: Histogram = _get_or_create_histogram(
    "stacklion_market_data_gateway_latency_seconds",
    "Latency of upstream market data gateway calls (seconds).",
    labelnames=("provider", "endpoint", "interval", "outcome"),
)

market_data_errors_total: Counter = _get_or_create_counter(
    "stacklion_market_data_errors_total",
    "Total errors encountered when calling upstream market data providers.",
    labelnames=("provider", "endpoint", "interval", "reason"),
)

# Cache hits/misses: UC calls .labels("historical_quotes") → one label.
market_data_cache_hits_total: Counter = _get_or_create_counter(
    "stacklion_market_data_cache_hits_total",
    "Cache hits for market data lookups.",
    labelnames=("source",),
)

market_data_cache_misses_total: Counter = _get_or_create_counter(
    "stacklion_market_data_cache_misses_total",
    "Cache misses for market data lookups.",
    labelnames=("source",),
)

# Historical UC latency: UC uses .time() directly → no labels.
usecase_historical_quotes_latency_seconds: Histogram = _get_or_create_histogram(
    "stacklion_usecase_historical_quotes_latency_seconds",
    "Latency of the historical quotes use case (seconds).",
)

market_data_304_total: Counter = _get_or_create_counter(
    "stacklion_market_data_304_total",
    "Total 304 Not Modified responses observed for market data endpoints.",
    labelnames=("provider", "endpoint"),
)

market_data_breaker_events_total: Counter = _get_or_create_counter(
    "stacklion_market_data_breaker_events_total",
    "Circuit-breaker events for market data providers.",
    labelnames=("provider", "endpoint", "state"),
)

market_data_http_status_total: Counter = _get_or_create_counter(
    "stacklion_market_data_http_status_total",
    "HTTP status codes returned by market data providers.",
    labelnames=("provider", "endpoint", "status_code"),
)

market_data_response_bytes: Histogram = _get_or_create_histogram(
    "stacklion_market_data_response_bytes",
    "Response payload size from market data providers (bytes).",
    labelnames=("provider", "endpoint"),
)

market_data_retries_total: Counter = _get_or_create_counter(
    "stacklion_market_data_retries_total",
    "Retries attempted for market data requests.",
    labelnames=("provider", "endpoint", "reason"),
)


# ---------------------------------------------------------------------------
# Observation context manager used by tests and gateways
# ---------------------------------------------------------------------------


@dataclass
class UpstreamObservation:
    """State captured while observing an upstream call.

    Attributes:
        provider: Upstream provider identifier (for labelling).
        endpoint: Logical endpoint name (for labelling).
        interval: Interval label (e.g. ``"1d"`` or ``"1m"``), if applicable.
        start: Monotonic start time in seconds.
        outcome: Outcome of the call (``"success"`` or ``"error"``).
        error_reason: Short, machine-readable error reason if any.
    """

    provider: str
    endpoint: str
    interval: str | None = None
    start: float = field(default_factory=perf_counter)
    # Monotonic start time
    outcome: str = "success"
    error_reason: str | None = None

    def mark_error(self, reason: str) -> None:
        """Mark the upstream call as failed with a given reason.

        Args:
            reason: Short, machine-readable error reason
                (e.g. ``"rate_limited"``).
        """
        self.outcome = "error"
        self.error_reason = reason


@contextmanager
def observe_upstream_request(
    *,
    provider: str,
    endpoint: str,
    interval: str | None = None,
) -> Generator[UpstreamObservation, None, None]:
    """Observe an upstream market data request.

    This context manager records:

    * a latency sample in
      :data:`stacklion_market_data_gateway_latency_seconds`, and
    * optionally an error increment in
      :data:`stacklion_market_data_errors_total` when
      :meth:`UpstreamObservation.mark_error` is invoked.

    Args:
        provider: Upstream provider identifier (e.g. ``"marketstack"``).
        endpoint: Logical endpoint name (e.g. ``"eod"`` or ``"intraday"``).
        interval: Optional interval label (e.g. ``"1d"`` or ``"1m"``).

    Yields:
        A mutable :class:`UpstreamObservation` instance that callers can use
        to signal errors via :meth:`UpstreamObservation.mark_error`.
    """
    obs = UpstreamObservation(provider=provider, endpoint=endpoint, interval=interval)
    try:
        yield obs
    except Exception:
        if obs.error_reason is None:
            obs.mark_error("exception")
        raise
    finally:
        elapsed = perf_counter() - obs.start

        with suppress(Exception):
            market_data_gateway_latency_seconds.labels(
                provider=obs.provider,
                endpoint=obs.endpoint,
                interval=obs.interval or "n/a",
                outcome=obs.outcome,
            ).observe(elapsed)

            if obs.error_reason is not None:
                market_data_errors_total.labels(
                    provider=obs.provider,
                    endpoint=obs.endpoint,
                    interval=obs.interval or "n/a",
                    reason=obs.error_reason,
                ).inc()


# ---------------------------------------------------------------------------
# Legacy helper API (keeps existing imports and tests working)
# ---------------------------------------------------------------------------


def get_market_data_cache_hits_total() -> Counter:
    """Return the cache-hits counter for market data lookups."""
    return market_data_cache_hits_total


def get_market_data_cache_misses_total() -> Counter:
    """Return the cache-misses counter for market data lookups."""
    return market_data_cache_misses_total


def get_usecase_historical_quotes_latency_seconds() -> Histogram:
    """Return the historical quotes use-case latency histogram."""
    return usecase_historical_quotes_latency_seconds


def get_market_data_errors_total() -> Counter:
    """Return the upstream market-data errors counter."""
    return market_data_errors_total


def get_market_data_gateway_latency_seconds() -> Histogram:
    """Return the upstream gateway latency histogram."""
    return market_data_gateway_latency_seconds


def get_market_data_304_total() -> Counter:
    """Return the 304 Not Modified counter for market data endpoints."""
    return market_data_304_total


def get_market_data_breaker_events_total() -> Counter:
    """Return the circuit-breaker events counter."""
    return market_data_breaker_events_total


def get_market_data_http_status_total() -> Counter:
    """Return the upstream HTTP status counter."""
    return market_data_http_status_total


def get_market_data_response_bytes() -> Histogram:
    """Return the upstream response-size histogram (bytes)."""
    return market_data_response_bytes


def get_market_data_retries_total() -> Counter:
    """Return the upstream retry counter."""
    return market_data_retries_total


def inc_market_data_error(*args: Any, **kwargs: Any) -> None:
    """Increment the market data error counter.

    This helper supports both the legacy positional API used in tests and the
    newer keyword-based API used in application code.

    Legacy positional usage
    -----------------------
    The unit test exercises the legacy form:

     inc_market_data_error("validation", "/v2/quotes/historical")

    This is interpreted as:

    * ``reason="validation"``
    * ``endpoint="/v2/quotes/historical"``
    * ``provider="api"``
    * ``interval="n/a"``

    Keyword usage
    -------------
    Newer code may use keyword arguments:

     inc_market_data_error(
         provider="marketstack",
         endpoint="eod",
         interval="1d",
         reason="rate_limited",
     )

    Args:
        *args: Optional positional arguments for the legacy form.
        **kwargs: Keyword arguments for the modern form.
    """
    # Legacy positional API: (reason, endpoint)
    if args and not kwargs:
        reason = str(args[0]) if len(args) >= 1 else "unknown"
        endpoint = str(args[1]) if len(args) >= 2 else "unknown"
        market_data_errors_total.labels(
            provider="api",
            endpoint=endpoint,
            interval="n/a",
            reason=reason,
        ).inc()
        return

    # Keyword-based API (preferred)
    provider = str(kwargs.get("provider", "unknown"))
    endpoint = str(kwargs.get("endpoint", "unknown"))
    interval = str(kwargs.get("interval", "n/a"))
    reason = str(kwargs.get("reason", "unknown"))

    market_data_errors_total.labels(
        provider=provider,
        endpoint=endpoint,
        interval=interval,
        reason=reason,
    ).inc()
