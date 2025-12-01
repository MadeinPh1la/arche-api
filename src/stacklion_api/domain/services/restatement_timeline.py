# src/stacklion_api/domain/services/restatement_timeline.py
# Copyright (c)
# SPDX-License-Identifier: MIT
"""Restatement metric timeline builder.

Purpose:
    Transform a restatement ledger (sequence of RestatementDelta hops) into a
    hop-aligned, per-metric time series suitable for modeling and analytics.

    Given a list of RestatementDelta instances representing adjacent hops in
    version space, this module produces a RestatementMetricTimeline value
    object aggregating:

        * Per-metric hop sequences of absolute deltas.
        * Restatement frequency per metric.
        * Maximum absolute delta per metric.
        * Aggregate timeline severity classification.

Design:
    * Pure domain logic: no logging, no HTTP, no persistence.
    * Operates on domain entities only (RestatementDelta, RestatementMetricTimeline).
    * Uses Decimal for all numeric values.
    * Deterministic ordering is enforced at the presenter / DTO layer; this
      module focuses on numeric correctness and invariants.

Layer:
    domain/services
"""

from __future__ import annotations

from collections import defaultdict
from collections.abc import Mapping, Sequence
from decimal import Decimal

from stacklion_api.domain.entities.edgar_restatement_delta import (
    RestatementDelta,
    RestatementMetricDelta,
)
from stacklion_api.domain.entities.restatement_metric_timeline import (
    RestatementMetricTimeline,
)
from stacklion_api.domain.enums.canonical_statement_metric import (
    CanonicalStatementMetric,
)
from stacklion_api.domain.enums.edgar import (
    FiscalPeriod,
    MaterialityClass,
    StatementType,
)


def _infer_identity(
    ledger: Sequence[RestatementDelta],
) -> tuple[str, StatementType, int, FiscalPeriod]:
    """Infer the statement identity from the first delta in the ledger.

    Assumes the ledger has been constructed for a single identity and that
    all elements share the same (cik, statement_type, fiscal_year,
    fiscal_period) attributes.

    Raises:
        ValueError:
            If the ledger is empty.
    """
    if not ledger:
        raise ValueError("_infer_identity() requires a non-empty ledger.")

    first = ledger[0]
    return first.cik, first.statement_type, first.fiscal_year, first.fiscal_period


def _classify_timeline(max_abs_delta: Decimal) -> MaterialityClass:
    """Classify aggregate materiality for the timeline.

    Note:
        Thresholds here are intentionally simple and can be aligned with the
        E8-D materiality profile logic. If E8-D exposes a central classifier,
        this function should delegate to it instead of duplicating thresholds.
    """
    if max_abs_delta <= Decimal("0"):
        return MaterialityClass.NONE

    # TODO: Align these thresholds with the E8-D materiality profile engine.
    if max_abs_delta < Decimal("1000000"):
        return MaterialityClass.LOW
    if max_abs_delta < Decimal("10000000"):
        return MaterialityClass.MEDIUM
    return MaterialityClass.HIGH


def build_restatement_metric_timeline(
    ledger: Sequence[RestatementDelta],
) -> RestatementMetricTimeline:
    """Build a hop-aligned restatement metric timeline from a ledger.

    Args:
        ledger:
            Ordered sequence of RestatementDelta instances. Each element is
            expected to expose a ``metrics`` mapping from canonical metric
            enum → metric-delta object with a ``diff`` attribute.

    Returns:
        RestatementMetricTimeline:
            Aggregated time-series representation of restatement behavior.

    Raises:
        ValueError:
            If ``ledger`` is empty.
    """
    if not ledger:
        raise ValueError("build_restatement_metric_timeline() requires a non-empty ledger.")

    cik, statement_type, fiscal_year, fiscal_period = _infer_identity(ledger)

    # metric_code -> list[(hop_index, abs_delta)]
    by_metric: dict[str, list[tuple[int, Decimal]]] = defaultdict(list)
    # metric_code -> count of non-zero hops
    restatement_frequency: dict[str, int] = defaultdict(int)
    # metric_code -> max abs delta
    per_metric_max_delta: dict[str, Decimal] = {}

    total_hops = len(ledger)

    for hop_index, delta in enumerate(ledger, start=1):
        # delta.metrics: Mapping[CanonicalStatementMetric, RestatementMetricDelta]
        metrics_map: Mapping[CanonicalStatementMetric, RestatementMetricDelta] = delta.metrics

        for metric_enum, metric_delta in metrics_map.items():
            metric_code = metric_enum.value

            diff = metric_delta.diff
            if diff is None:
                # No numeric diff; skip this metric for this hop.
                continue

            # Domain contract: diff is a Decimal.
            abs_delta = diff.copy_abs()

            by_metric[metric_code].append((hop_index, abs_delta))

            if abs_delta != 0:
                restatement_frequency[metric_code] += 1

            current_max = per_metric_max_delta.get(metric_code)
            if current_max is None or abs_delta > current_max:
                per_metric_max_delta[metric_code] = abs_delta

    # Aggregate max across all metrics for severity classification.
    global_max = max(per_metric_max_delta.values(), default=Decimal("0"))
    timeline_severity = _classify_timeline(global_max)

    return RestatementMetricTimeline(
        cik=cik,
        statement_type=statement_type,
        fiscal_year=fiscal_year,
        fiscal_period=fiscal_period,
        by_metric={k: list(v) for k, v in by_metric.items()},
        total_hops=total_hops,
        restatement_frequency=dict(restatement_frequency),
        per_metric_max_delta=per_metric_max_delta,
        timeline_severity=timeline_severity,
    )


__all__ = ["build_restatement_metric_timeline"]
