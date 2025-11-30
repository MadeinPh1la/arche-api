# src/stacklion_api/application/use_cases/statements/get_restatement_delta_between_versions.py
# Copyright (c)
# SPDX-License-Identifier: MIT
"""Use case: Restatement delta between specific statement versions.

Purpose:
    Given a company, statement identity, and optional version-sequence bounds,
    compute an analytics-grade restatement delta across canonical metrics using
    the domain statement ledger engine's selection rules.

Layer:
    application

Notes:
    - Read-only use case; depends on the EDGAR statements repository via the
      UnitOfWork abstraction.
    - Delegates version selection and metric-level delta computation to the
      domain-level ``compute_restatement_delta_between_versions`` helper.
    - Returns a DTO-oriented projection suitable for HTTP presenters.
"""

from __future__ import annotations

import logging
from collections.abc import Sequence
from dataclasses import dataclass
from typing import Any, cast

from stacklion_api.application.schemas.dto.edgar import (
    ComputeRestatementDeltaResultDTO,
    RestatementMetricDeltaDTO,
    RestatementSummaryDTO,
)
from stacklion_api.application.uow import UnitOfWork
from stacklion_api.domain.entities.edgar_restatement_delta import RestatementDelta
from stacklion_api.domain.entities.edgar_statement_version import EdgarStatementVersion
from stacklion_api.domain.enums.canonical_statement_metric import CanonicalStatementMetric
from stacklion_api.domain.enums.edgar import FiscalPeriod, StatementType
from stacklion_api.domain.exceptions.edgar import EdgarIngestionError, EdgarMappingError
from stacklion_api.domain.interfaces.repositories.edgar_statements_repository import (
    EdgarStatementsRepository as EdgarStatementsRepositoryProtocol,
)
from stacklion_api.domain.services.statement_ledger_delta_engine import (
    compute_restatement_delta_between_versions,
)

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class GetRestatementDeltaBetweenVersionsRequest:
    """Request parameters for restatement delta between versions.

    Attributes:
        cik:
            Central Index Key for the filer.
        statement_type:
            Statement type (income, balance sheet, cash flow, etc.).
        fiscal_year:
            Fiscal year associated with the statement.
        fiscal_period:
            Fiscal period within the year (e.g., FY, Q1, Q2).
        from_version_sequence:
            Optional lower-bound version sequence (inclusive). When None, the
            domain engine applies default selection rules.
        to_version_sequence:
            Optional upper-bound version sequence (inclusive). When None, the
            domain engine applies default selection rules.
        metrics:
            Optional subset of canonical metrics to consider. When None, the
            domain engine uses its default behavior (all intersecting metrics).
    """

    cik: str
    statement_type: StatementType
    fiscal_year: int
    fiscal_period: FiscalPeriod
    from_version_sequence: int | None = None
    to_version_sequence: int | None = None
    metrics: Sequence[CanonicalStatementMetric] | None = None


class GetRestatementDeltaBetweenVersionsUseCase:
    """Compute a restatement delta between specific statement versions.

    This use case loads all EDGAR statement versions for a given
    (cik, statement_type, fiscal_year, fiscal_period) identity and
    delegates to the domain statement ledger engine to select the
    appropriate version range and compute per-metric restatement deltas.

    Args:
        uow:
            Application :class:`UnitOfWork` abstraction used to resolve
            the EDGAR statements repository.

    Returns:
        Instances of this use case return a
        :class:`ComputeRestatementDeltaResultDTO` when
        :meth:`execute` is called.

    Raises:
        EdgarMappingError:
            If request parameters are invalid (for example, empty CIK,
            non-positive fiscal_year, or non-positive version bounds).
        EdgarIngestionError:
            If no statement versions exist or there are fewer than two
            normalized versions available to compute a delta.
    """

    def __init__(self, uow: UnitOfWork) -> None:
        """Initialize the use case.

        Args:
            uow: Application UnitOfWork abstraction used to resolve repositories.
        """
        self._uow = uow

    async def execute(
        self,
        req: GetRestatementDeltaBetweenVersionsRequest,
    ) -> ComputeRestatementDeltaResultDTO:
        """Execute the restatement delta computation.

        Args:
            req: Parameters describing the target statement and version bounds.

        Returns:
            A :class:`ComputeRestatementDeltaResultDTO` containing the selected
            version range, high-level summary, and per-metric deltas.

        Raises:
            EdgarMappingError:
                If request parameters are invalid (empty CIK, non-positive
                fiscal_year, non-positive version sequences).
            EdgarIngestionError:
                If no statement versions exist or there are insufficient
                normalized versions to compute a delta.
        """
        cik = req.cik.strip()
        if not cik:
            raise EdgarMappingError(
                "CIK must not be empty for get_restatement_delta_between_versions().",
            )

        if req.fiscal_year <= 0:
            raise EdgarMappingError(
                "fiscal_year must be a positive integer for get_restatement_delta_between_versions().",
                details={"fiscal_year": req.fiscal_year},
            )

        if req.from_version_sequence is not None and req.from_version_sequence <= 0:
            raise EdgarMappingError(
                "from_version_sequence must be a positive integer when provided.",
                details={"from_version_sequence": req.from_version_sequence},
            )

        if req.to_version_sequence is not None and req.to_version_sequence <= 0:
            raise EdgarMappingError(
                "to_version_sequence must be a positive integer when provided.",
                details={"to_version_sequence": req.to_version_sequence},
            )

        logger.info(
            "edgar.get_restatement_delta_between_versions.start",
            extra={
                "cik": cik,
                "statement_type": req.statement_type.value,
                "fiscal_year": req.fiscal_year,
                "fiscal_period": req.fiscal_period.value,
                "from_version_sequence": req.from_version_sequence,
                "to_version_sequence": req.to_version_sequence,
                "metrics": [m.value for m in (req.metrics or [])],
            },
        )

        async with self._uow as tx:
            statements_repo = _get_edgar_statements_repository(tx)
            versions = await statements_repo.list_statement_versions_for_company(
                cik=cik,
                statement_type=req.statement_type,
                fiscal_year=req.fiscal_year,
                fiscal_period=req.fiscal_period,
            )

        if not versions:
            raise EdgarIngestionError(
                "No EDGAR statement versions found for restatement delta between versions.",
                details={
                    "cik": cik,
                    "statement_type": req.statement_type.value,
                    "fiscal_year": req.fiscal_year,
                    "fiscal_period": req.fiscal_period.value,
                },
            )

        _ensure_minimum_normalized_versions(versions, cik, req)

        delta: RestatementDelta = compute_restatement_delta_between_versions(
            versions=versions,
            from_version_sequence=req.from_version_sequence,
            to_version_sequence=req.to_version_sequence,
            metrics=req.metrics,
        )

        summary_dto = _build_summary_from_delta(delta)
        metric_dtos = _build_metric_deltas_from_delta(delta)

        result_dto = ComputeRestatementDeltaResultDTO(
            cik=delta.cik,
            statement_type=delta.statement_type,
            fiscal_year=delta.fiscal_year,
            fiscal_period=delta.fiscal_period,
            from_version_sequence=delta.from_version_sequence,
            to_version_sequence=delta.to_version_sequence,
            summary=summary_dto,
            deltas=metric_dtos,
        )

        logger.info(
            "edgar.get_restatement_delta_between_versions.success",
            extra={
                "cik": delta.cik,
                "statement_type": delta.statement_type.value,
                "statement_date": delta.statement_date.isoformat(),
                "fiscal_year": delta.fiscal_year,
                "fiscal_period": delta.fiscal_period.value,
                "from_version_sequence": delta.from_version_sequence,
                "to_version_sequence": delta.to_version_sequence,
                "changed_metrics": [m.value for m in delta.metrics],
            },
        )

        return result_dto


def _ensure_minimum_normalized_versions(
    versions: Sequence[EdgarStatementVersion],
    cik: str,
    req: GetRestatementDeltaBetweenVersionsRequest,
) -> None:
    """Ensure there are at least two normalized versions available."""
    normalized_versions = [v for v in versions if v.normalized_payload is not None]
    if len(normalized_versions) < 2:
        raise EdgarIngestionError(
            "At least two normalized EDGAR statement versions are required to "
            "compute a restatement delta between versions.",
            details={
                "cik": cik,
                "statement_type": req.statement_type.value,
                "fiscal_year": req.fiscal_year,
                "fiscal_period": req.fiscal_period.value,
                "normalized_version_sequences": sorted(
                    v.version_sequence for v in normalized_versions
                ),
            },
        )


def _build_summary_from_delta(delta: RestatementDelta) -> RestatementSummaryDTO:
    """Build a high-level summary DTO from a RestatementDelta."""
    total_metrics_changed = len(delta.metrics)
    total_metrics_compared = total_metrics_changed
    has_material_change = total_metrics_changed > 0

    return RestatementSummaryDTO(
        total_metrics_compared=total_metrics_compared,
        total_metrics_changed=total_metrics_changed,
        has_material_change=has_material_change,
    )


def _build_metric_deltas_from_delta(
    delta: RestatementDelta,
) -> list[RestatementMetricDeltaDTO]:
    """Build per-metric RestatementMetricDeltaDTOs from a RestatementDelta."""
    metric_dtos: list[RestatementMetricDeltaDTO] = []

    for metric, md in sorted(delta.metrics.items(), key=lambda kv: kv[0].value):
        metric_dtos.append(
            RestatementMetricDeltaDTO(
                metric=metric.value,
                old_value=str(md.old) if md.old is not None else None,
                new_value=str(md.new) if md.new is not None else None,
                diff=str(md.diff) if md.diff is not None else None,
            ),
        )

    return metric_dtos


def _get_edgar_statements_repository(tx: Any) -> EdgarStatementsRepositoryProtocol:
    """Resolve the EDGAR statements repository via the UnitOfWork.

    Test doubles may expose `repo`, `statements_repo`, or `_repo` attributes
    instead of a full repository registry. Prefer those when present to keep
    tests and fakes simple.
    """
    if hasattr(tx, "repo"):
        return cast(EdgarStatementsRepositoryProtocol, tx.repo)
    if hasattr(tx, "statements_repo"):
        return cast(EdgarStatementsRepositoryProtocol, tx.statements_repo)
    if hasattr(tx, "_repo"):
        return cast(EdgarStatementsRepositoryProtocol, tx._repo)

    return cast(
        EdgarStatementsRepositoryProtocol,
        tx.get_repository(EdgarStatementsRepositoryProtocol),
    )
