# Copyright (c) Stacklion.
# SPDX-License-Identifier: MIT
"""EDGAR metrics.

Purpose:
    Provide Prometheus-style metrics for EDGAR external API calls:
      * Latency histograms.
      * Error counters by reason.
      * HTTP status distribution.
      * Response size histograms.
      * Retry and circuit-breaker event counters.

Design:
    - If prometheus_client is unavailable, exposes no-op counters/histograms.
    - Functions return singleton metric instances, mirroring the
      metrics_market_data module shape.
"""

from __future__ import annotations

from typing import Any

try:  # pragma: no cover - import guarded, behavior covered via no-op fallback.
    from prometheus_client import Counter, Histogram
except Exception:  # pragma: no cover

    class _NoopCounter:
        def labels(self, *args: Any, **kwargs: Any) -> _NoopCounter:
            return self

        def inc(self, *args: Any, **kwargs: Any) -> None:
            return None

    class _NoopHistogram:
        def labels(self, *args: Any, **kwargs: Any) -> _NoopHistogram:
            return self

        def observe(self, *args: Any, **kwargs: Any) -> None:
            return None

    Counter = _NoopCounter  # type: ignore[assignment]
    Histogram = _NoopHistogram  # type: ignore[assignment]


_edgar_gateway_latency_seconds: Any | None = None
_edgar_errors_total: Any | None = None
_edgar_http_status_total: Any | None = None
_edgar_response_bytes: Any | None = None
_edgar_retries_total: Any | None = None
_edgar_304_total: Any | None = None
_edgar_breaker_events_total: Any | None = None


def get_edgar_gateway_latency_seconds() -> Any:
    """Return (and lazily create) the EDGAR gateway latency histogram."""
    global _edgar_gateway_latency_seconds
    if _edgar_gateway_latency_seconds is None:
        _edgar_gateway_latency_seconds = Histogram(
            "edgar_gateway_latency_seconds",
            "Latency of EDGAR gateway calls in seconds.",
            ["provider", "endpoint", "outcome"],
        )
    return _edgar_gateway_latency_seconds


def get_edgar_errors_total() -> Any:
    """Return (and lazily create) the EDGAR error counter."""
    global _edgar_errors_total
    if _edgar_errors_total is None:
        _edgar_errors_total = Counter(
            "edgar_errors_total",
            "Total number of EDGAR client/gateway errors.",
            ["provider", "endpoint", "reason"],
        )
    return _edgar_errors_total


def get_edgar_http_status_total() -> Any:
    """Return (and lazily create) the EDGAR HTTP status counter."""
    global _edgar_http_status_total
    if _edgar_http_status_total is None:
        _edgar_http_status_total = Counter(
            "edgar_http_status_total",
            "EDGAR HTTP responses by status code.",
            ["provider", "endpoint", "status"],
        )
    return _edgar_http_status_total


def get_edgar_response_bytes() -> Any:
    """Return (and lazily create) the EDGAR response-bytes histogram."""
    global _edgar_response_bytes
    if _edgar_response_bytes is None:
        _edgar_response_bytes = Histogram(
            "edgar_response_bytes",
            "Size of EDGAR HTTP responses in bytes.",
            ["provider", "endpoint"],
        )
    return _edgar_response_bytes


def get_edgar_retries_total() -> Any:
    """Return (and lazily create) the EDGAR retry counter."""
    global _edgar_retries_total
    if _edgar_retries_total is None:
        _edgar_retries_total = Counter(
            "edgar_retries_total",
            "Total number of EDGAR retries.",
            ["provider", "endpoint", "reason"],
        )
    return _edgar_retries_total


def get_edgar_304_total() -> Any:
    """Return (and lazily create) the EDGAR 304 (not modified) counter."""
    global _edgar_304_total
    if _edgar_304_total is None:
        _edgar_304_total = Counter(
            "edgar_304_total",
            "Total number of EDGAR 304 (Not Modified) responses.",
            ["provider", "endpoint"],
        )
    return _edgar_304_total


def get_edgar_breaker_events_total() -> Any:
    """Return (and lazily create) the EDGAR circuit-breaker events counter."""
    global _edgar_breaker_events_total
    if _edgar_breaker_events_total is None:
        _edgar_breaker_events_total = Counter(
            "edgar_breaker_events_total",
            "Total EDGAR circuit breaker state transitions.",
            ["provider", "endpoint", "state"],
        )
    return _edgar_breaker_events_total
