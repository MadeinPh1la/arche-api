# src/stacklion_api/application/use_cases/statements/get_restatement_timeline.py
# Copyright (c)
# SPDX-License-Identifier: MIT
"""Use case: Restatement metric timeline for a statement identity.

Purpose:
    Build a hop-aligned restatement timeline across the normalized statement
    version history for a given (cik, statement_type, fiscal_year,
    fiscal_period) identity.

    The resulting timeline exposes per-metric sequences of absolute deltas,
    restatement frequencies, and aggregate severity suitable for analytics
    and modeling workflows.

Design:
    * Pure application-layer orchestration:
        - Validation of request parameters.
        - Use of UnitOfWork and EDGAR statements repository.
        - Delegation to domain ledger and timeline builders.
        - Mapping of domain entities into DTOs.
    * No HTTP, logging, or persistence details are embedded here.

Layer:
    application/use_cases
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import cast

from stacklion_api.application.schemas.dto.edgar import RestatementMetricTimelineDTO
from stacklion_api.application.uow import UnitOfWork
from stacklion_api.domain.entities.restatement_metric_timeline import RestatementMetricTimeline
from stacklion_api.domain.enums.edgar import FiscalPeriod, StatementType
from stacklion_api.domain.exceptions.edgar import EdgarIngestionError, EdgarMappingError
from stacklion_api.domain.interfaces.repositories.edgar_statements_repository import (
    EdgarStatementsRepository,
)
from stacklion_api.domain.services.restatement_timeline import (
    build_restatement_metric_timeline,
)
from stacklion_api.domain.services.statement_ledger_delta_engine import build_restatement_ledger


@dataclass(slots=True)
class GetRestatementTimelineRequest:
    """Parameter object describing the restatement timeline identity.

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


class GetRestatementTimelineUseCase:
    """Use case building a restatement metric timeline across statement versions.

    Args:
        uow:
            Unit-of-work instance providing access to the
            :class:`EdgarStatementsRepository`.
    """

    def __init__(self, uow: UnitOfWork) -> None:
        """Initialize the restatement timeline use case.

        Args:
            uow:
                Unit-of-work instance providing access to the
                :class:`EdgarStatementsRepository`.
        """
        self._uow = uow

    async def execute(
        self,
        req: GetRestatementTimelineRequest,
    ) -> RestatementMetricTimelineDTO:
        """Execute restatement timeline construction.

        Args:
            req:
                Parameters describing the target statement identity.

        Returns:
            A :class:`RestatementMetricTimelineDTO` representing the full
            hop-aligned restatement timeline for the requested identity.

        Raises:
            EdgarMappingError:
                If request parameters are invalid (empty CIK, non-positive
                fiscal_year).
            EdgarIngestionError:
                If there are no statement versions, fewer than two normalized
                versions, or an empty ledger from which to build a timeline.
        """
        cik = req.cik.strip()
        if not cik:
            raise EdgarMappingError(
                "CIK must not be empty for get_restatement_timeline().",
            )

        if req.fiscal_year <= 0:
            raise EdgarMappingError(
                "fiscal_year must be a positive integer for get_restatement_timeline().",
                details={"fiscal_year": req.fiscal_year},
            )

        # Fetch versions for the identity via repository.
        async with self._uow as uow:
            repo = cast(
                EdgarStatementsRepository,
                uow.get_repository(EdgarStatementsRepository),
            )
            versions = await repo.list_statement_versions_for_company(
                cik=cik,
                statement_type=req.statement_type,
                fiscal_year=req.fiscal_year,
                fiscal_period=req.fiscal_period,
            )

        if not versions:
            raise EdgarIngestionError(
                "No statement versions available to build restatement timeline.",
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
                "build a restatement timeline.",
                details={
                    "cik": cik,
                    "statement_type": req.statement_type.value,
                    "fiscal_year": req.fiscal_year,
                    "fiscal_period": req.fiscal_period.value,
                    "normalized_versions": len(normalized_versions),
                },
            )

        # Build the restatement ledger using the domain engine. This returns
        # a sequence of RestatementDelta instances ordered by version sequence.
        ledger = build_restatement_ledger(
            versions=normalized_versions,
            metrics=None,
        )

        if not ledger:
            # Defensive guard: the current domain behavior returns an empty
            # ledger only when there are fewer than two normalized versions,
            # but we keep this check explicit for clarity.
            raise EdgarIngestionError(
                "Restatement ledger is empty; cannot build restatement timeline.",
                details={
                    "cik": cik,
                    "statement_type": req.statement_type.value,
                    "fiscal_year": req.fiscal_year,
                    "fiscal_period": req.fiscal_period.value,
                },
            )

        # Build the hop-aligned metric timeline from the ledger.
        timeline: RestatementMetricTimeline = build_restatement_metric_timeline(ledger)

        # Map domain entity → DTO, stringifying Decimal values.
        dto_by_metric: dict[str, list[tuple[int, str]]] = {}
        for metric_code, hops in timeline.by_metric.items():
            dto_by_metric[metric_code] = [
                (hop_index, str(abs_delta)) for hop_index, abs_delta in hops
            ]

        dto_per_metric_max_delta: dict[str, str] = {
            metric_code: str(max_delta)
            for metric_code, max_delta in timeline.per_metric_max_delta.items()
        }

        return RestatementMetricTimelineDTO(
            cik=timeline.cik,
            statement_type=timeline.statement_type,
            fiscal_year=timeline.fiscal_year,
            fiscal_period=timeline.fiscal_period,
            by_metric=dto_by_metric,
            restatement_frequency=dict(timeline.restatement_frequency),
            per_metric_max_delta=dto_per_metric_max_delta,
            total_hops=timeline.total_hops,
            timeline_severity=timeline.timeline_severity,
        )
