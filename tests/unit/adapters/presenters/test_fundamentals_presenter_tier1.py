# tests/unit/adapters/presenters/test_fundamentals_presenter_tier1.py
# Copyright (c)
# SPDX-License-Identifier: MIT
"""Presenter-level tests for Tier-1 fundamentals HTTP surfaces."""

from __future__ import annotations

from datetime import date
from decimal import Decimal

from stacklion_api.adapters.presenters.fundamentals_presenter import (
    present_fundamentals_time_series,
)
from stacklion_api.domain.entities.edgar_fundamentals_timeseries import (
    FundamentalsTimeSeriesPoint,
)
from stacklion_api.domain.enums.edgar import (
    AccountingStandard,
    FiscalPeriod,
    StatementType,
)
from stacklion_api.domain.services.canonical_metric_registry import (
    get_tier1_metrics_for_statement_type,
)


def test_presenter_includes_tier1_metrics_in_http_payload() -> None:
    """Tier-1 canonical metrics should flow through to HTTP metrics mapping.

    This test uses the canonical metric registry to construct a fundamentals
    point with Tier-1 metrics for the income statement and verifies that the
    presenter exposes those metrics using the canonical string codes.
    """
    statement_type = StatementType.INCOME_STATEMENT
    tier1_metrics = get_tier1_metrics_for_statement_type(statement_type)

    # Build a domain fundamentals point with Tier-1 metrics only.
    metrics = {metric: Decimal("1.0") for metric in tier1_metrics}

    point = FundamentalsTimeSeriesPoint(
        cik="0000320193",
        statement_type=statement_type,
        accounting_standard=AccountingStandard.US_GAAP,
        statement_date=date(2024, 9, 28),
        fiscal_year=2024,
        fiscal_period=FiscalPeriod.FY,
        currency="USD",
        metrics=metrics,
        normalized_payload_version_sequence=1,
    )

    envelope = present_fundamentals_time_series(points=[point], page=1, page_size=10)

    assert envelope.total == 1
    assert len(envelope.items) == 1

    http_point = envelope.items[0]

    # HTTP metrics keys must be the canonical metric codes (Enum .value).
    http_metric_keys = set(http_point.metrics.keys())
    expected_keys = {metric.value for metric in tier1_metrics}

    # All Tier-1 metrics should be present in the HTTP payload.
    assert expected_keys <= http_metric_keys

    # Values should be decimal strings.
    for code in expected_keys:
        value = http_point.metrics[code]
        assert isinstance(value, str)
        assert value == "1.0"
