# src/arche_api/domain/entities/edgar_derived_timeseries.py
# Copyright (c)
# SPDX-License-Identifier: MIT
"""Derived metrics time series domain entities.

Purpose:
    Represent a modeling-friendly derived-metrics time series built on top of
    canonical normalized EDGAR statement payloads. Each point corresponds to
    a statement period (company, statement_date, fiscal_period) and carries a
    bundle of derived metrics such as margins, growth, and returns.

Layer:
    domain

Notes:
    - This module is transport-agnostic and persistence-agnostic.
    - Numeric values are expressed as :class:`decimal.Decimal` in the domain.
    - Deterministic ordering is defined by a pure helper function.
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from datetime import date
from decimal import Decimal

from arche_api.domain.enums.derived_metric import DerivedMetric
from arche_api.domain.enums.edgar import AccountingStandard, FiscalPeriod, StatementType


@dataclass(frozen=True)
class DerivedMetricsTimeSeriesPoint:
    """Single derived-metrics time-series point.

    Attributes:
        cik:
            Company CIK associated with this point. Must be a non-empty string
            after stripping whitespace.
        statement_type:
            Statement type that served as the primary source for the derived
            metrics (e.g., INCOME_STATEMENT).
        accounting_standard:
            Accounting standard (e.g., US_GAAP, IFRS).
        statement_date:
            Reporting period end date.
        fiscal_year:
            Fiscal year associated with the statement. Must be >= 1.
        fiscal_period:
            Fiscal period (e.g., FY, Q1, Q2).
        currency:
            ISO 4217 currency code (e.g., "USD") for all monetary metrics.
        metrics:
            Mapping from derived metric identifiers to their computed values.
            Values may be ``None`` when inputs are insufficient to compute a
            given metric.
        normalized_payload_version_sequence:
            Version sequence of the canonical normalized payload used to drive
            the computation for this point. Must be >= 1.
    """

    cik: str
    statement_type: StatementType
    accounting_standard: AccountingStandard
    statement_date: date
    fiscal_year: int
    fiscal_period: FiscalPeriod
    currency: str
    metrics: Mapping[DerivedMetric, Decimal | None]
    normalized_payload_version_sequence: int

    def __post_init__(self) -> None:
        """Enforce basic invariants for derived metrics time-series points.

        Raises:
            ValueError: If any core invariants are violated (e.g., empty CIK,
                fiscal_year < 1, invalid metric keys, or non-Decimal values).
        """
        # Because the dataclass is frozen, we only validate; no mutation.
        if not self.cik or not self.cik.strip():
            raise ValueError("cik must be a non-empty string")

        if self.fiscal_year < 1:
            raise ValueError("fiscal_year must be >= 1")

        if self.normalized_payload_version_sequence < 1:
            raise ValueError("normalized_payload_version_sequence must be >= 1")

        # Defensive type checks on metrics mapping.
        for metric, value in self.metrics.items():
            if not isinstance(metric, DerivedMetric):
                raise ValueError("metrics keys must be DerivedMetric enum members")
            if value is not None and not isinstance(value, Decimal):
                raise ValueError(
                    "metrics values must be decimal.Decimal or None "
                    f"(got {type(value)!r} for metric {metric!r})",
                )


def build_derived_metrics_timeseries(
    points: Iterable[DerivedMetricsTimeSeriesPoint],
) -> list[DerivedMetricsTimeSeriesPoint]:
    """Return a deterministically ordered list of derived-metrics points.

    Ordering:
        - cik (lexicographically)
        - statement_date ascending
        - fiscal_period value
        - normalized_payload_version_sequence ascending

    Args:
        points:
            Iterable of derived-metrics points, potentially unordered.

    Returns:
        List of points sorted according to the canonical ordering.
    """
    return sorted(
        points,
        key=lambda p: (
            p.cik,
            p.statement_date,
            p.fiscal_period.value,
            p.normalized_payload_version_sequence,
        ),
    )


__all__ = ["DerivedMetricsTimeSeriesPoint", "build_derived_metrics_timeseries"]
