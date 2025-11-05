# Copyright (c) Stacklion.
# SPDX-License-Identifier: MIT
from __future__ import annotations

from prometheus_client import generate_latest

from stacklion_api.infrastructure.observability.metrics_market_data import (
    observe_upstream_request,
)


def test_observe_upstream_request_marks_error_and_records_latency() -> None:
    # Before: read current counter for sanity
    before = generate_latest().decode("utf-8")

    with observe_upstream_request(provider="marketstack", endpoint="eod", interval="1d") as obs:
        obs.mark_error(reason="rate_limited")

    after = generate_latest().decode("utf-8")

    # The gateway latency histogram should have observed at least one bucket line
    assert "stacklion_market_data_gateway_latency_seconds_bucket" in after

    # Error counter increment with reason label present
    assert "stacklion_market_data_errors_total" in after
    assert 'reason="rate_limited"' in after or "rate_limited" in after

    # Ensure counter advanced (weak assertion: text changed)
    assert after != before
