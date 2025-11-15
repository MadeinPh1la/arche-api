from __future__ import annotations

from stacklion_api.infrastructure.observability.metrics import (
    get_data_lag_seconds,
    get_ingest_errors_total,
    get_ingest_latency_seconds,
    get_ingest_rows_total,
    get_readyz_db_latency_seconds,
    get_readyz_redis_latency_seconds,
)


def test_readyz_histograms_reuse_singleton_and_observe() -> None:
    """Readyz histograms should be singletons per registry and accept observations."""
    h1 = get_readyz_db_latency_seconds()
    h2 = get_readyz_db_latency_seconds()
    assert h1 is h2

    # Should be callable without throwing.
    h1.observe(0.012)

    r1 = get_readyz_redis_latency_seconds()
    r2 = get_readyz_redis_latency_seconds()
    assert r1 is r2
    r1.observe(0.005)


def test_ingest_metrics_basic_usage() -> None:
    """Ingest metrics helpers should return working, label-based collectors."""
    latency = get_ingest_latency_seconds()
    latency.labels(source="marketstack", endpoint="intraday").observe(0.123)

    rows = get_ingest_rows_total()
    rows.labels(source="marketstack", endpoint="intraday", result="success").inc()

    errors = get_ingest_errors_total()
    errors.labels(source="marketstack", endpoint="intraday", reason="validation").inc()

    lag = get_data_lag_seconds()
    lag.labels(source="marketstack", endpoint="intraday").observe(5.0)
