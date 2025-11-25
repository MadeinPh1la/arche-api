# src/stacklion_api/domain/entities/edgar_restatement_delta.py
# Copyright (c) Stacklion.
# SPDX-License-Identifier: MIT
"""
EDGAR restatement delta domain entities and helpers.

Purpose:
    Provide a deterministic, analytics-grade representation of version-over-
    version changes for normalized EDGAR financial statements, as well as
    pure functions to compute those deltas from canonical normalized payloads.

Layer:
    domain

Notes:
    - Depends only on domain entities/value objects and enums.
    - Does not know about persistence, HTTP, or transport concerns.
    - Designed to be stable and replayable for backtests and modeling.
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
from stacklion_api.domain.exceptions.edgar import EdgarMappingError


@dataclass(frozen=True)
class RestatementMetricDelta:
    """Delta for a single canonical metric between two statement versions.

    Attributes:
        metric: Canonical metric identifier.
        old: Value in the "from" version (before restatement).
        new: Value in the "to" version (after restatement).
        diff: new - old, or None if either side is missing.
    """

    metric: CanonicalStatementMetric
    old: Decimal | None
    new: Decimal | None
    diff: Decimal | None


@dataclass(frozen=True)
class RestatementDelta:
    """Version-over-version restatement delta for a normalized statement.

    This value object captures the delta between two normalized statement
    payloads for the same (cik, statement_type, statement_date, frequency)
    identity tuple.

    Attributes:
        cik: Central Index Key for the filer.
        statement_type: Statement type (income, balance sheet, cash flow, etc.).
        accounting_standard: Accounting standard (e.g., US_GAAP, IFRS).
        statement_date: Reporting period end date.
        fiscal_year: Fiscal year associated with the statement.
        fiscal_period: Fiscal period (e.g., FY, Q1, Q2).
        currency: ISO 4217 currency code for all monetary values.
        from_version_sequence:
            Source version sequence for the "from" payload. Typically the
            earlier (pre-restatement) version.
        to_version_sequence:
            Source version sequence for the "to" payload. Typically the later
            (post-restatement) version.
        metrics:
            Mapping of canonical metrics to their per-metric deltas. Only
            metrics present in both payloads are included by default.
    """

    cik: str
    statement_type: StatementType
    accounting_standard: AccountingStandard
    statement_date: date
    fiscal_year: int
    fiscal_period: FiscalPeriod
    currency: str
    from_version_sequence: int
    to_version_sequence: int
    metrics: Mapping[CanonicalStatementMetric, RestatementMetricDelta]


def compute_restatement_delta(
    from_payload: CanonicalStatementPayload,
    to_payload: CanonicalStatementPayload,
    metrics: Iterable[CanonicalStatementMetric] | None = None,
) -> RestatementDelta:
    """Compute a restatement delta between two normalized statement payloads.

    Both payloads must refer to the same logical statement identity:

        (cik, statement_type, accounting_standard,
         statement_date, fiscal_year, fiscal_period, currency)

    If any of these attributes differ, an :class:`EdgarMappingError` is raised.

    By default, only metrics that are present in *both* payloads and whose
    values differ are included in the resulting :class:`RestatementDelta`.
    This keeps the structure tightly focused on actual changes.

    Args:
        from_payload:
            Canonical normalized payload representing the "before" version
            (typically the earlier sequence).
        to_payload:
            Canonical normalized payload representing the "after" version
            (typically the later sequence).
        metrics:
            Optional explicit set of canonical metrics to consider. When
            provided, only these metrics are inspected. When None, the
            intersection of keys present in both payloads' ``core_metrics``
            is used.

    Returns:
        A :class:`RestatementDelta` describing per-metric deltas between the
        two payloads.

    Raises:
        EdgarMappingError:
            If the payloads do not share the same identity tuple, or if
            invariants required for deterministic delta computation are
            violated.
    """
    _ensure_payload_identity_match(from_payload=from_payload, to_payload=to_payload)

    from_core = from_payload.core_metrics
    to_core = to_payload.core_metrics

    if metrics is not None:
        candidate_metrics = list(metrics)
    else:
        # Restrict to metrics that appear in both payloads; we do not try to
        # infer semantics for "added" or "removed" metrics here. Those can be
        # derived by comparing the individual payloads if needed.
        candidate_metrics = sorted(
            set(from_core.keys()) & set(to_core.keys()),
            key=lambda m: m.value,
        )

    deltas: dict[CanonicalStatementMetric, RestatementMetricDelta] = {}

    for metric in candidate_metrics:
        old_value = from_core.get(metric)
        new_value = to_core.get(metric)

        # If either side is missing, we do not include this metric by default.
        if old_value is None or new_value is None:
            continue

        if new_value == old_value:
            # No effective change; skip to keep the structure focused on
            # changed metrics only.
            continue

        diff = new_value - old_value
        deltas[metric] = RestatementMetricDelta(
            metric=metric,
            old=old_value,
            new=new_value,
            diff=diff,
        )

    return RestatementDelta(
        cik=from_payload.cik,
        statement_type=from_payload.statement_type,
        accounting_standard=from_payload.accounting_standard,
        statement_date=from_payload.statement_date,
        fiscal_year=from_payload.fiscal_year,
        fiscal_period=from_payload.fiscal_period,
        currency=from_payload.currency,
        from_version_sequence=from_payload.source_version_sequence,
        to_version_sequence=to_payload.source_version_sequence,
        metrics=deltas,
    )


def _ensure_payload_identity_match(
    *,
    from_payload: CanonicalStatementPayload,
    to_payload: CanonicalStatementPayload,
) -> None:
    """Ensure two payloads refer to the same logical statement identity.

    Args:
        from_payload: "Before" version payload.
        to_payload: "After" version payload.

    Raises:
        EdgarMappingError:
            If any of the identity fields differ between the two payloads.
    """
    mismatches: dict[str, tuple[object, object]] = {}

    if from_payload.cik != to_payload.cik:
        mismatches["cik"] = (from_payload.cik, to_payload.cik)
    if from_payload.statement_type is not to_payload.statement_type:
        mismatches["statement_type"] = (from_payload.statement_type, to_payload.statement_type)
    if from_payload.accounting_standard is not to_payload.accounting_standard:
        mismatches["accounting_standard"] = (
            from_payload.accounting_standard,
            to_payload.accounting_standard,
        )
    if from_payload.statement_date != to_payload.statement_date:
        mismatches["statement_date"] = (
            from_payload.statement_date,
            to_payload.statement_date,
        )
    if from_payload.fiscal_year != to_payload.fiscal_year:
        mismatches["fiscal_year"] = (from_payload.fiscal_year, to_payload.fiscal_year)
    if from_payload.fiscal_period is not to_payload.fiscal_period:
        mismatches["fiscal_period"] = (from_payload.fiscal_period, to_payload.fiscal_period)
    if from_payload.currency != to_payload.currency:
        mismatches["currency"] = (from_payload.currency, to_payload.currency)

    if mismatches:
        # We keep the error surface simple and deterministic; callers that need
        # more detail can inspect the "details" mapping.
        raise EdgarMappingError(
            "CanonicalStatementPayload identity mismatch for restatement delta.",
            details={k: {"from": v[0], "to": v[1]} for k, v in mismatches.items()},
        )


__all__ = ["RestatementMetricDelta", "RestatementDelta", "compute_restatement_delta"]
