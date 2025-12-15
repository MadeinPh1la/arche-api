# src/arche_api/domain/entities/restatement_metric_timeline.py
# Copyright (c)
# SPDX-License-Identifier: MIT
"""Restatement metric timeline value object.

Purpose:
    Represent a hop-aligned, per-metric time series of absolute restatement
    deltas across an EDGAR restatement ledger. This value object is designed
    for analytics and modeling consumers that need:

        * Per-metric sequences of absolute deltas across hops.
        * Restatement frequency per metric.
        * Maximum absolute delta per metric.
        * Aggregate severity classification for the overall timeline.

Design:
    * Pure domain entity: no logging, no HTTP, no persistence.
    * All numeric values are :class:`decimal.Decimal`.
    * Invariants are enforced via :meth:`__post_init__`.

Layer:
    domain/entities
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from decimal import Decimal

from arche_api.domain.enums.edgar import FiscalPeriod, MaterialityClass, StatementType


@dataclass(frozen=True)
class RestatementMetricTimeline:
    """Hop-aligned severity timeline for restatements by metric.

    Attributes:
        cik:
            Central Index Key for the filer whose restatement behavior this
            timeline describes.
        statement_type:
            Statement type (income statement, balance sheet, cash flow, etc.).
        fiscal_year:
            Fiscal year associated with the statement identity.
        fiscal_period:
            Fiscal period within the fiscal year (for example, FY, Q1, Q2).
        by_metric:
            Mapping from canonical metric code to a sequence of
            ``(hop_index, abs_delta)`` pairs, where:

                * ``hop_index`` is a 1-based index into the underlying
                  restatement ledger hops.
                * ``abs_delta`` is the absolute value of the numeric restatement
                  delta for that metric at that hop.

        total_hops:
            Total number of restatement hops represented in this timeline.
            Must be a positive integer.
        restatement_frequency:
            Mapping from metric code to the count of hops where the absolute
            delta was non-zero.
        per_metric_max_delta:
            Mapping from metric code to the maximum absolute delta observed
            across all hops for that metric.
        timeline_severity:
            Aggregate severity classification derived from the maximum absolute
            delta across all metrics.
    """

    cik: str
    statement_type: StatementType
    fiscal_year: int
    fiscal_period: FiscalPeriod
    by_metric: Mapping[str, Sequence[tuple[int, Decimal]]]
    total_hops: int
    restatement_frequency: Mapping[str, int]
    per_metric_max_delta: Mapping[str, Decimal]
    timeline_severity: MaterialityClass

    def __post_init__(self) -> None:
        """Enforce basic invariants for the value object.

        Raises:
            ValueError:
                If ``total_hops`` is not positive, hop indices are out of range,
                absolute deltas are negative, or the metric mappings are
                inconsistent.
        """
        if self.total_hops <= 0:
            raise ValueError("RestatementMetricTimeline.total_hops must be positive.")

        metric_keys = set(self.by_metric.keys())

        # Validate hop indices and absolute deltas.
        for metric_code, hops in self.by_metric.items():
            for hop_index, abs_delta in hops:
                if hop_index <= 0 or hop_index > self.total_hops:
                    raise ValueError(
                        f"Hop index {hop_index} for metric '{metric_code}' is out of "
                        f"range 1..{self.total_hops}."
                    )
                if abs_delta < 0:
                    raise ValueError(
                        f"Absolute delta for metric '{metric_code}' at hop "
                        f"{hop_index} must be non-negative."
                    )

        # restatement_frequency keys must be a subset of by_metric keys.
        freq_keys = set(self.restatement_frequency.keys())
        extra_freq = freq_keys - metric_keys
        if extra_freq:
            raise ValueError(
                "restatement_frequency contains metrics not present in by_metric: "
                + ", ".join(sorted(extra_freq))
            )

        # per_metric_max_delta keys must be a subset of by_metric keys.
        max_keys = set(self.per_metric_max_delta.keys())
        extra_max = max_keys - metric_keys
        if extra_max:
            raise ValueError(
                "per_metric_max_delta contains metrics not present in by_metric: "
                + ", ".join(sorted(extra_max))
            )


__all__ = ["RestatementMetricTimeline"]
