# Copyright (c) Stacklion.
# SPDX-License-Identifier: MIT
"""EDGAR fundamentals time-series domain entities and helpers.

Purpose:
    Provide a stable, panel-friendly representation of normalized EDGAR
    fundamentals for use in analytics-grade time-series endpoints.

Layer:
    domain

Notes:
    - Operates purely on CanonicalStatementPayload inputs.
    - Does not know about HTTP, persistence, or MCP envelopes.
    - Intended to be consumed by application-level DTOs and presenters.
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from datetime import date
from decimal import Decimal

from stacklion_api.domain.entities.canonical_statement_payload import (
    CanonicalStatementPayload,
)
from stacklion_api.domain.enums.canonical_statement_metric import (
    CanonicalStatementMetric,
)
from stacklion_api.domain.enums.edgar import AccountingStandard, FiscalPeriod, StatementType


@dataclass(frozen=True)
class FundamentalsTimeSeriesPoint:
    """Single time-series point for normalized EDGAR fundamentals.

    Attributes:
        cik: Central Index Key for the entity (non-empty string).
        statement_type: Statement type (income, balance sheet, cash flow, etc.).
        accounting_standard: Accounting standard (e.g., US_GAAP, IFRS).
        statement_date: Reporting period end date.
        fiscal_year: Fiscal year associated with the statement (must be > 0).
        fiscal_period: Fiscal period within the year (e.g., Q1, Q2, FY).
        currency:
            ISO 4217 currency code (non-empty, already normalized by upstream
            mappers).
        metrics:
            Mapping from canonical metrics to their values for this period.
            Only metrics actually present in the source payload are included.
        normalized_payload_version_sequence:
            Source version sequence of the underlying canonical payload. This
            allows callers to reason about restatements over time and must be
            a positive integer.
    """

    cik: str
    statement_type: StatementType
    accounting_standard: AccountingStandard
    statement_date: date
    fiscal_year: int
    fiscal_period: FiscalPeriod
    currency: str
    metrics: Mapping[CanonicalStatementMetric, Decimal]
    normalized_payload_version_sequence: int

    def __post_init__(self) -> None:
        """Enforce core invariants for fundamentals time-series points."""
        if not isinstance(self.cik, str) or not self.cik.strip():
            raise ValueError("FundamentalsTimeSeriesPoint.cik must be a non-empty string.")

        if self.fiscal_year <= 0:
            raise ValueError(
                "FundamentalsTimeSeriesPoint.fiscal_year must be a positive integer.",
            )

        if not isinstance(self.currency, str) or not self.currency.strip():
            raise ValueError(
                "FundamentalsTimeSeriesPoint.currency must be a non-empty ISO code.",
            )

        if self.normalized_payload_version_sequence <= 0:
            raise ValueError(
                "FundamentalsTimeSeriesPoint.normalized_payload_version_sequence "
                "must be a positive integer.",
            )

        # Basic shape checks for metrics. We deliberately keep this light-weight
        # and defensive to avoid surprising callers.
        for metric, value in self.metrics.items():
            if not isinstance(metric, CanonicalStatementMetric):
                raise TypeError(
                    "FundamentalsTimeSeriesPoint.metrics keys must be CanonicalStatementMetric "
                    f"instances; got {type(metric)!r}.",
                )
            if not isinstance(value, Decimal):
                raise TypeError(
                    "FundamentalsTimeSeriesPoint.metrics values must be Decimal instances; "
                    f"got {type(value)!r}.",
                )


def build_fundamentals_timeseries(
    payloads: Iterable[CanonicalStatementPayload],
    metrics: Iterable[CanonicalStatementMetric] | None = None,
) -> list[FundamentalsTimeSeriesPoint]:
    """Build a deterministic fundamentals time series from canonical payloads.

    This helper converts a collection of :class:`CanonicalStatementPayload`
    instances into a sorted list of :class:`FundamentalsTimeSeriesPoint`
    suitable for application DTOs and HTTP endpoints.

    Behavior:
        * If ``metrics`` is None, all metrics present in each payload's
          ``core_metrics`` are included for that point.
        * If ``metrics`` is provided, only those metrics are considered; any
          metric not present in a particular payload is simply omitted from
          that point's mapping.
        * The returned list is sorted deterministically by:
              (cik ASC, statement_date ASC, fiscal_year ASC,
               fiscal_period.value ASC, normalized_payload_version_sequence ASC)

    Args:
        payloads:
            Iterable of canonical statement payloads, typically obtained from
            persisted normalized statement versions.
        metrics:
            Optional explicit set of canonical metrics to include. When None,
            all metrics present in each payload are used for that payload.

    Returns:
        Deterministically ordered list of time-series points.
    """
    metric_filter = list(metrics) if metrics is not None else None

    points: list[FundamentalsTimeSeriesPoint] = []

    for payload in payloads:
        if metric_filter is None:
            metric_keys = list(payload.core_metrics.keys())
        else:
            metric_keys = [m for m in metric_filter if m in payload.core_metrics]

        values: dict[CanonicalStatementMetric, Decimal] = {}
        for metric in metric_keys:
            value = payload.core_metrics.get(metric)
            if value is None:
                # We do not emit missing metrics; absence is more informative
                # than a null placeholder for modeling consumers.
                continue
            values[metric] = value

        point = FundamentalsTimeSeriesPoint(
            cik=payload.cik,
            statement_type=payload.statement_type,
            accounting_standard=payload.accounting_standard,
            statement_date=payload.statement_date,
            fiscal_year=payload.fiscal_year,
            fiscal_period=payload.fiscal_period,
            currency=payload.currency,
            metrics=values,
            normalized_payload_version_sequence=payload.source_version_sequence,
        )
        points.append(point)

    points.sort(
        key=lambda p: (
            p.cik,
            p.statement_date,
            p.fiscal_year,
            p.fiscal_period.value,
            p.normalized_payload_version_sequence,
        ),
    )

    return points


__all__ = ["FundamentalsTimeSeriesPoint", "build_fundamentals_timeseries"]
