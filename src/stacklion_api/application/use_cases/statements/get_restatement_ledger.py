# src/stacklion_api/application/use_cases/statements/get_restatement_ledger.py
# Copyright (c)
# SPDX-License-Identifier: MIT
"""Restatement ledger use case.

Purpose:
    Build a restatement ledger across the normalized statement version history
    for a given (cik, statement_type, fiscal_year, fiscal_period) identity.

    The ledger is expressed as an ordered sequence of "hops" between adjacent
    statement versions. Each hop carries:
        * from_version_sequence / to_version_sequence
        * a summary with total metrics compared / changed
        * optional per-metric deltas (old / new / diff)

Design:
    * Pure application-layer orchestration:
        - Validation of request parameters.
        - Use of UnitOfWork and EDGAR statements repository.
        - Construction of domain-level ledger objects.
    * No HTTP, logging, or persistence details are embedded here.
      Routers, controllers, and presenters own transport/presentation concerns.

Layer:
    application/use_cases
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from decimal import Decimal
from typing import cast

from stacklion_api.application.uow import UnitOfWork
from stacklion_api.domain.entities.canonical_statement_payload import (
    CanonicalStatementPayload,
)
from stacklion_api.domain.entities.edgar_statement_version import EdgarStatementVersion
from stacklion_api.domain.enums.canonical_statement_metric import CanonicalStatementMetric
from stacklion_api.domain.enums.edgar import FiscalPeriod, StatementType
from stacklion_api.domain.exceptions.edgar import EdgarIngestionError, EdgarMappingError
from stacklion_api.domain.interfaces.repositories.edgar_statements_repository import (
    EdgarStatementsRepository,
)

# ---------------------------------------------------------------------------
# Request / result models
# ---------------------------------------------------------------------------


@dataclass(slots=True)
class GetRestatementLedgerRequest:
    """Parameter object describing the ledger identity.

    Attributes:
        cik:
            Company CIK string, typically zero-padded. Leading/trailing
            whitespace is tolerated but stripped.
        statement_type:
            Statement type for the target identity (e.g., INCOME_STATEMENT).
        fiscal_year:
            Fiscal year (must be a positive integer).
        fiscal_period:
            Fiscal period code (e.g., FY, Q1, Q2, Q3, Q4).
    """

    cik: str
    statement_type: StatementType
    fiscal_year: int
    fiscal_period: FiscalPeriod


@dataclass(slots=True)
class MetricDelta:
    """Per-metric restatement delta for a single hop."""

    metric: CanonicalStatementMetric
    old: Decimal | None
    new: Decimal | None
    diff: Decimal | None


@dataclass(slots=True)
class RestatementHopDelta:
    """Detailed deltas between two statement versions."""

    from_version_sequence: int
    to_version_sequence: int
    metrics: Mapping[CanonicalStatementMetric, MetricDelta]


@dataclass(slots=True)
class RestatementSummary:
    """Aggregate summary for a restatement hop."""

    total_metrics_compared: int
    total_metrics_changed: int
    has_material_change: bool


@dataclass(slots=True)
class RestatementLedgerEntry:
    """Single hop in the restatement ledger between adjacent versions."""

    from_version_sequence: int
    to_version_sequence: int
    summary: RestatementSummary
    # Optional per-metric deltas; callers may ignore detailed deltas.
    delta: RestatementHopDelta | None = None


@dataclass(slots=True)
class RestatementLedgerResult:
    """Complete restatement ledger for a statement identity."""

    cik: str
    statement_type: StatementType
    fiscal_year: int
    fiscal_period: FiscalPeriod
    entries: Sequence[RestatementLedgerEntry]


# ---------------------------------------------------------------------------
# Use case
# ---------------------------------------------------------------------------


class GetRestatementLedgerUseCase:
    """Use case building a restatement ledger across statement versions.

    Args:
        uow:
            Unit-of-work instance providing access to the
            :class:`EdgarStatementsRepository`.
    """

    def __init__(self, uow: UnitOfWork) -> None:
        """Initialize the restatement ledger use case.

        Args:
            uow:
                Unit-of-work instance providing access to the
                :class:`EdgarStatementsRepository`.
        """
        self._uow = uow

    async def execute(self, req: GetRestatementLedgerRequest) -> RestatementLedgerResult:
        """Execute restatement ledger construction.

        Args:
            req:
                Parameters describing the target statement identity.

        Returns:
            A :class:`RestatementLedgerResult` representing the full ledger for
            the requested identity.

        Raises:
            EdgarMappingError:
                If request parameters are invalid (empty CIK, non-positive
                fiscal_year).
            EdgarIngestionError:
                If there are no statement versions or fewer than two normalized
                versions available to build a ledger.
        """
        cik = req.cik.strip()
        if not cik:
            raise EdgarMappingError(
                "CIK must not be empty for get_restatement_ledger().",
            )

        if req.fiscal_year <= 0:
            raise EdgarMappingError(
                "fiscal_year must be a positive integer for get_restatement_ledger().",
                details={"fiscal_year": req.fiscal_year},
            )

        # Fetch versions for the identity via repository.
        async with self._uow as uow:
            repo = cast(
                EdgarStatementsRepository,
                uow.get_repository(EdgarStatementsRepository),
            )
            versions: Sequence[EdgarStatementVersion] = (
                await repo.list_statement_versions_for_company(
                    cik=cik,
                    statement_type=req.statement_type,
                    fiscal_year=req.fiscal_year,
                    fiscal_period=req.fiscal_period,
                )
            )

        if not versions:
            raise EdgarIngestionError(
                "No statement versions available to build restatement ledger.",
                details={
                    "cik": cik,
                    "statement_type": req.statement_type.value,
                    "fiscal_year": req.fiscal_year,
                    "fiscal_period": req.fiscal_period.value,
                },
            )

        # Only normalized versions can participate in a quantitative ledger.
        normalized_versions = [v for v in versions if v.normalized_payload is not None]
        if len(normalized_versions) < 2:
            raise EdgarIngestionError(
                "At least two normalized statement versions are required to "
                "build a restatement ledger.",
                details={
                    "cik": cik,
                    "statement_type": req.statement_type.value,
                    "fiscal_year": req.fiscal_year,
                    "fiscal_period": req.fiscal_period.value,
                    "normalized_versions": len(normalized_versions),
                },
            )

        # Deterministic ordering by version_sequence ascending so hops are
        # strictly from earlier → later versions.
        ordered = sorted(normalized_versions, key=lambda v: v.version_sequence)

        entries: list[RestatementLedgerEntry] = []
        for idx in range(len(ordered) - 1):
            from_version = ordered[idx]
            to_version = ordered[idx + 1]

            entry = self._build_entry(
                from_version=from_version,
                to_version=to_version,
            )
            entries.append(entry)

        return RestatementLedgerResult(
            cik=cik,
            statement_type=req.statement_type,
            fiscal_year=req.fiscal_year,
            fiscal_period=req.fiscal_period,
            entries=entries,
        )

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _build_entry(
        *,
        from_version: EdgarStatementVersion,
        to_version: EdgarStatementVersion,
    ) -> RestatementLedgerEntry:
        """Construct a single ledger entry between two versions."""
        from_payload = cast(CanonicalStatementPayload, from_version.normalized_payload)
        to_payload = cast(CanonicalStatementPayload, to_version.normalized_payload)

        # For now, we focus on core_metrics. This keeps typing simple and
        # aligns with current tests which only exercise canonical metrics
        # such as REVENUE.
        metrics_from: Mapping[CanonicalStatementMetric, Decimal] = from_payload.core_metrics
        metrics_to: Mapping[CanonicalStatementMetric, Decimal] = to_payload.core_metrics

        all_metrics = set(metrics_from.keys()) | set(metrics_to.keys())

        metric_deltas: dict[CanonicalStatementMetric, MetricDelta] = {}
        total_compared = 0
        total_changed = 0

        for metric in sorted(all_metrics, key=lambda m: m.value):
            old_val = metrics_from.get(metric)
            new_val = metrics_to.get(metric)

            if old_val is None and new_val is None:
                # Nothing to compare for this metric; skip.
                continue

            total_compared += 1

            diff: Decimal | None = (
                new_val - old_val if old_val is not None and new_val is not None else None
            )

            if diff is not None and diff != 0:
                total_changed += 1

            metric_deltas[metric] = MetricDelta(
                metric=metric,
                old=old_val,
                new=new_val,
                diff=diff,
            )

        summary = RestatementSummary(
            total_metrics_compared=total_compared,
            total_metrics_changed=total_changed,
            has_material_change=total_changed > 0,
        )

        delta = RestatementHopDelta(
            from_version_sequence=from_version.version_sequence,
            to_version_sequence=to_version.version_sequence,
            metrics=metric_deltas,
        )

        return RestatementLedgerEntry(
            from_version_sequence=from_version.version_sequence,
            to_version_sequence=to_version.version_sequence,
            summary=summary,
            delta=delta,
        )
