# src/arche_api/domain/entities/restatement_delta.py
# Copyright (c)
# SPDX-License-Identifier: MIT
"""Restatement delta entity.

Purpose:
    Represent the differences between two normalized financial-statement
    versions (original → restated) at the canonical metric level. Used by the
    Normalized Statement Payload Engine to provide restatement lineage and
    quantitative deltas for advanced modeling.

Layer:
    domain

Notes:
    - Pure domain logic only.
    - Missing metrics are treated as zero.
    - All numeric values are :class:`decimal.Decimal`.
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from datetime import date
from decimal import Decimal

from arche_api.domain.entities.canonical_statement_payload import CanonicalStatementPayload
from arche_api.domain.enums.canonical_statement_metric import CanonicalStatementMetric
from arche_api.domain.enums.edgar import FiscalPeriod, StatementType


@dataclass(frozen=True)
class RestatementMetricDelta:
    """Per-metric numeric restatement delta.

    Attributes:
        metric: The canonical metric being compared.
        old_value: Value before the restatement.
        new_value: Value after the restatement.
        diff: new_value - old_value.
    """

    metric: CanonicalStatementMetric
    old_value: Decimal
    new_value: Decimal
    diff: Decimal

    def __post_init__(self) -> None:
        """Enforce invariants."""
        if self.diff != self.new_value - self.old_value:
            raise ValueError("Invariant violation: diff must equal new_value - old_value.")
        if not isinstance(self.metric, CanonicalStatementMetric):
            raise ValueError("metric must be a CanonicalStatementMetric.")

    @classmethod
    def from_values(
        cls,
        *,
        metric: CanonicalStatementMetric,
        old_value: Decimal,
        new_value: Decimal,
    ) -> RestatementMetricDelta:
        """Construct a delta from raw values.

        Args:
            metric: Canonical metric identifier.
            old_value: Old (pre-restatement) numeric value.
            new_value: New (post-restatement) numeric value.

        Returns:
            A RestatementMetricDelta with calculated diff.
        """
        return cls(
            metric=metric,
            old_value=old_value,
            new_value=new_value,
            diff=new_value - old_value,
        )

    @property
    def has_change(self) -> bool:
        """Return True if the metric changed."""
        return self.diff != 0


@dataclass(frozen=True)
class RestatementSummary:
    """Aggregate summary for a restatement delta hop.

    Attributes:
        total_metrics_compared: Number of metrics examined.
        total_metrics_changed: Number of metrics exhibiting non-zero change.
        has_material_change: True if any metric changed.
    """

    total_metrics_compared: int
    total_metrics_changed: int
    has_material_change: bool

    def __post_init__(self) -> None:
        """Enforce invariants."""
        if self.total_metrics_compared < 0:
            raise ValueError("total_metrics_compared must be non-negative.")
        if self.total_metrics_changed < 0:
            raise ValueError("total_metrics_changed must be non-negative.")
        if self.total_metrics_changed > self.total_metrics_compared:
            raise ValueError("Changed metric count cannot exceed compared metrics.")

    @classmethod
    def from_deltas(
        cls,
        *,
        total_compared: int,
        deltas: Mapping[CanonicalStatementMetric, RestatementMetricDelta],
    ) -> RestatementSummary:
        """Build a summary from an explicit metric universe and delta set."""
        changed = sum(1 for d in deltas.values() if d.has_change)
        return cls(
            total_metrics_compared=total_compared,
            total_metrics_changed=changed,
            has_material_change=changed > 0,
        )


@dataclass(frozen=True)
class RestatementDeltaIdentity:
    """Identity tuple for a restatement delta hop.

    Attributes:
        cik: Company CIK.
        statement_type: Statement type.
        fiscal_year: Fiscal year.
        fiscal_period: Fiscal period (FY, Q1, etc.).
        statement_date: Optional statement date if available.
        from_version_sequence: Lower-bound version sequence of the hop.
        to_version_sequence: Upper-bound version sequence of the hop.
    """

    cik: str
    statement_type: StatementType
    fiscal_year: int
    fiscal_period: FiscalPeriod
    statement_date: date | None = None
    from_version_sequence: int | None = None
    to_version_sequence: int | None = None

    def __post_init__(self) -> None:
        """Enforce invariants."""
        if not isinstance(self.statement_type, StatementType):
            raise ValueError("statement_type must be a StatementType.")
        if not isinstance(self.fiscal_period, FiscalPeriod):
            raise ValueError("fiscal_period must be a FiscalPeriod.")


@dataclass(frozen=True)
class RestatementDelta:
    """Domain entity representing a restatement delta between two versions.

    Attributes:
        identity: Identity tuple for the restatement hop.
        deltas: Mapping of metric → per-metric delta. Only changed metrics appear.
        summary: High-level summary counts and materiality flag.
    """

    identity: RestatementDeltaIdentity
    deltas: Mapping[CanonicalStatementMetric, RestatementMetricDelta]
    summary: RestatementSummary

    def __post_init__(self) -> None:
        """Enforce invariants."""
        if not isinstance(self.identity, RestatementDeltaIdentity):
            raise ValueError("identity must be a RestatementDeltaIdentity.")
        for metric, delta in self.deltas.items():
            if not isinstance(metric, CanonicalStatementMetric):
                raise ValueError("deltas keys must be CanonicalStatementMetric.")
            if not isinstance(delta, RestatementMetricDelta):
                raise ValueError("deltas values must be RestatementMetricDelta.")

    @classmethod
    def from_payloads(
        cls,
        *,
        cik: str,
        statement_type: StatementType,
        fiscal_year: int,
        fiscal_period: FiscalPeriod,
        original: CanonicalStatementPayload | None,
        restated: CanonicalStatementPayload | None,
        statement_date: date | None = None,
        from_version_sequence: int | None = None,
        to_version_sequence: int | None = None,
        metrics: Iterable[CanonicalStatementMetric] | None = None,
    ) -> RestatementDelta:
        """Compute a restatement delta from two canonical payloads.

        Args:
            cik: Company CIK.
            statement_type: Statement type.
            fiscal_year: Fiscal year.
            fiscal_period: Fiscal period.
            original: Original (pre-restatement) payload.
            restated: Restated (post-restatement) payload.
            statement_date: Optional statement date override.
            from_version_sequence: Optional lower-bound version sequence.
            to_version_sequence: Optional upper-bound version sequence.
            metrics: Optional explicit subset of metrics to compare.

        Returns:
            A RestatementDelta with computed deltas and a summary.
        """
        # Treat missing payloads as empty.
        original_core = original.core_metrics if original is not None else {}
        restated_core = restated.core_metrics if restated is not None else {}

        # Build universe.
        if metrics is None:
            universe = set(original_core.keys()) | set(restated_core.keys())
        else:
            universe = set(metrics)

        ordered_metrics = sorted(universe, key=lambda m: m.value)

        deltas: dict[CanonicalStatementMetric, RestatementMetricDelta] = {}

        for metric in ordered_metrics:
            old_value = original_core.get(metric, Decimal("0"))
            new_value = restated_core.get(metric, Decimal("0"))

            if new_value != old_value:
                deltas[metric] = RestatementMetricDelta.from_values(
                    metric=metric,
                    old_value=old_value,
                    new_value=new_value,
                )

        summary = RestatementSummary.from_deltas(
            total_compared=len(ordered_metrics),
            deltas=deltas,
        )

        identity = RestatementDeltaIdentity(
            cik=cik,
            statement_type=statement_type,
            fiscal_year=fiscal_year,
            fiscal_period=fiscal_period,
            statement_date=statement_date,
            from_version_sequence=from_version_sequence,
            to_version_sequence=to_version_sequence,
        )

        return cls(
            identity=identity,
            deltas=deltas,
            summary=summary,
        )
