from __future__ import annotations

import pytest

from stacklion_api.infrastructure.observability.metrics_market_data import (
    get_market_data_304_total,
    get_market_data_breaker_events_total,
    get_market_data_cache_hits_total,
    get_market_data_cache_misses_total,
    get_market_data_errors_total,
    get_market_data_gateway_latency_seconds,
    get_market_data_http_status_total,
    get_market_data_response_bytes,
    get_market_data_retries_total,
    get_usecase_historical_quotes_latency_seconds,
    inc_market_data_error,
    market_data_errors_total,
    market_data_gateway_latency_seconds,
    observe_upstream_request,
)


def _find_sample(counter, **labels: str) -> bool:
    """Return True if any sample on the counter has all the given label values."""
    for metric in counter.collect():
        for sample in metric.samples:
            if all(sample.labels.get(k) == v for k, v in labels.items()):
                return True
    return False


def test_observe_upstream_request_success_records_latency() -> None:
    """Successful upstream call should record a latency sample with success outcome."""
    with observe_upstream_request(
        provider="marketstack",
        endpoint="eod",
        interval="1d",
    ):
        # no-op body; we just want to observe latency
        pass

    assert _find_sample(
        market_data_gateway_latency_seconds,
        provider="marketstack",
        endpoint="eod",
        interval="1d",
        outcome="success",
    )


def test_observe_upstream_request_exception_records_error() -> None:
    """Exception inside context should mark error and increment error metrics."""
    with (
        pytest.raises(RuntimeError),
        observe_upstream_request(
            provider="marketstack",
            endpoint="intraday",
            interval="1m",
        ),
    ):
        raise RuntimeError("boom")

    assert _find_sample(
        market_data_gateway_latency_seconds,
        provider="marketstack",
        endpoint="intraday",
        interval="1m",
        outcome="error",
    )
    assert _find_sample(
        market_data_errors_total,
        provider="marketstack",
        endpoint="intraday",
        interval="1m",
        reason="exception",
    )


def test_inc_market_data_error_legacy_positional() -> None:
    """Legacy positional API should map to provider='api', interval='n/a'."""
    inc_market_data_error("validation", "/v1/quotes/historical")

    assert _find_sample(
        market_data_errors_total,
        provider="api",
        endpoint="/v1/quotes/historical",
        interval="n/a",
        reason="validation",
    )


def test_inc_market_data_error_keyword_api() -> None:
    """Keyword API should map labels as provided."""
    inc_market_data_error(
        provider="marketstack",
        endpoint="eod",
        interval="1d",
        reason="rate_limited",
    )

    assert _find_sample(
        market_data_errors_total,
        provider="marketstack",
        endpoint="eod",
        interval="1d",
        reason="rate_limited",
    )


def test_legacy_accessors_return_core_collectors() -> None:
    """Legacy get_* accessors should return the same core collectors."""
    assert get_market_data_cache_hits_total() is not None
    assert get_market_data_cache_misses_total() is not None
    assert get_usecase_historical_quotes_latency_seconds() is not None
    assert get_market_data_errors_total() is not None
    assert get_market_data_gateway_latency_seconds() is not None
    assert get_market_data_304_total() is not None
    assert get_market_data_breaker_events_total() is not None
    assert get_market_data_http_status_total() is not None
    assert get_market_data_response_bytes() is not None
    assert get_market_data_retries_total() is not None
