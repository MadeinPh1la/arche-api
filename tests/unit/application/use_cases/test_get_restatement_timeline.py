# tests/unit/application/use_cases/test_get_restatement_timeline.py
# Copyright (c)
# SPDX-License-Identifier: MIT
"""Unit tests related to restatement timelines.

Scope:
    - Exercise the restatement timeline domain service to ensure basic
      invariants and classification behavior are stable.
    - Satisfy architecture conventions requiring a test module for
      get_restatement_timeline use case.

Note:
    These tests focus on the domain service wiring and invariants rather than
    the full use-case orchestration.
"""


from __future__ import annotations

from collections.abc import Sequence
from decimal import Decimal
from typing import cast

from arche_api.domain.entities.edgar_restatement_delta import RestatementDelta
from arche_api.domain.enums.edgar import FiscalPeriod, MaterialityClass, StatementType
from arche_api.domain.services.restatement_timeline import build_restatement_metric_timeline


class _FakeMetricEnum:
    """Simple stand-in for CanonicalStatementMetric with a value attribute."""

    def __init__(self, value: str) -> None:
        self.value = value


class _FakeMetricDelta:
    """Simple stand-in for RestatementMetricDelta with a diff attribute."""

    def __init__(self, diff: Decimal | None) -> None:
        self.diff = diff


class _FakeDelta:
    """Duck-typed stand-in for RestatementDelta used by the timeline builder."""

    def __init__(self, diff: Decimal) -> None:
        self.cik = "0000123456"
        self.statement_type = StatementType.INCOME_STATEMENT
        self.fiscal_year = 2024
        self.fiscal_period = FiscalPeriod.FY
        # Simulate metrics mapping: {metric_enum -> metric_delta}
        metric_enum = _FakeMetricEnum("revenue")
        metric_delta = _FakeMetricDelta(diff)
        self.metrics = {metric_enum: metric_delta}


def test_build_restatement_metric_timeline_single_hop_non_zero_delta() -> None:
    """Timeline builder should classify a simple single-hop non-zero delta."""
    ledger: list[_FakeDelta] = [_FakeDelta(Decimal("1500000"))]

    # Cast to the expected type for static analysis; runtime uses duck typing.
    timeline = build_restatement_metric_timeline(
        cast(Sequence[RestatementDelta], ledger),
    )

    assert timeline.cik == "0000123456"
    assert timeline.statement_type is StatementType.INCOME_STATEMENT
    assert timeline.fiscal_year == 2024
    assert timeline.fiscal_period is FiscalPeriod.FY
    assert timeline.total_hops == 1

    # We expect one metric with one hop entry.
    assert set(timeline.by_metric.keys()) == {"revenue"}
    hops = list(timeline.by_metric["revenue"])
    assert hops == [(1, Decimal("1500000"))]

    # Frequency and max-delta should reflect the single non-zero hop.
    assert timeline.restatement_frequency["revenue"] == 1
    assert timeline.per_metric_max_delta["revenue"] == Decimal("1500000")

    # With a 1.5M absolute delta, the aggregate severity should at least be MEDIUM
    # given the current threshold implementation.
    assert timeline.timeline_severity in {
        MaterialityClass.MEDIUM,
        MaterialityClass.HIGH,
    }


def test_build_restatement_metric_timeline_zero_delta_yields_none_severity() -> None:
    """Timeline builder should treat zero deltas as non-material."""
    ledger: list[_FakeDelta] = [_FakeDelta(Decimal("0"))]

    timeline = build_restatement_metric_timeline(
        cast(Sequence[RestatementDelta], ledger),
    )

    assert timeline.total_hops == 1
    # If all deltas are exactly zero, global max is 0 → NONE.
    assert timeline.timeline_severity is MaterialityClass.NONE
