# src/stacklion_api/application/use_cases/statements/compute_restatement_delta.py
# Copyright (c)
# SPDX-License-Identifier: MIT
"""Use case: Compute restatement deltas between two statement versions.

Purpose:
    Given a company, statement identity, and two version sequences, compute
    an analytics-grade restatement delta across canonical metrics using the
    normalized payload engine.

Layer:
    application

Notes:
    - This use case is read-only and depends on the EDGAR statements
      repository via the UnitOfWork abstraction.
    - It delegates metric-level delta computation to the domain-level
      `compute_restatement_delta` helper.
    - Concrete repositories live in the adapters layer and are resolved
      indirectly via the UnitOfWork to preserve layering.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Any, cast

from stacklion_api.application.uow import UnitOfWork
from stacklion_api.domain.entities.edgar_restatement_delta import (
    RestatementDelta,
    compute_restatement_delta,
)
from stacklion_api.domain.entities.edgar_statement_version import EdgarStatementVersion
from stacklion_api.domain.enums.canonical_statement_metric import CanonicalStatementMetric
from stacklion_api.domain.enums.edgar import FiscalPeriod, StatementType
from stacklion_api.domain.exceptions.edgar import EdgarIngestionError, EdgarMappingError
from stacklion_api.domain.interfaces.repositories.edgar_statements_repository import (
    EdgarStatementsRepository as EdgarStatementsRepositoryProtocol,
)

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class ComputeRestatementDeltaRequest:
    """Request parameters for restatement delta computation.

    Attributes:
        cik: Central Index Key for the filer.
        statement_type: Statement type (income, balance sheet, cash flow, etc.).
        fiscal_year: Fiscal year associated with the statement.
        fiscal_period: Fiscal period within the year (e.g., FY, Q1, Q2).
        from_version_sequence:
            Sequence number for the "before" version (typically smaller).
        to_version_sequence:
            Sequence number for the "after" version (typically larger).
        metrics:
            Optional subset of canonical metrics to consider. When None, the
            intersection of metrics present in both payloads is used.
    """

    cik: str
    statement_type: StatementType
    fiscal_year: int
    fiscal_period: FiscalPeriod
    from_version_sequence: int
    to_version_sequence: int
    metrics: tuple[CanonicalStatementMetric, ...] | None = None


@dataclass(frozen=True)
class ComputeRestatementDeltaResult:
    """Result for restatement delta computation.

    Attributes:
        from_version: Statement version used as the "before" baseline.
        to_version: Statement version used as the "after" baseline.
        delta: Domain-level restatement delta, including per-metric changes.
    """

    from_version: EdgarStatementVersion
    to_version: EdgarStatementVersion
    delta: RestatementDelta


class ComputeRestatementDeltaUseCase:
    """Compute deltas between two versions of the same EDGAR statement.

    Args:
        uow: Unit-of-work used to access the EDGAR statements repository.

    Returns:
        EdgarRestatementDelta: Domain object describing numeric deltas between
        the requested version pair, scoped to the requested metrics.

    Raises:
        EdgarIngestionError: If either version is missing, lacks a normalized
            payload, or the repository lookup fails.
    """

    def __init__(self, uow: UnitOfWork) -> None:
        """Initialize the use case.

        Args:
            uow: Application UnitOfWork abstraction used to resolve repositories.
        """
        self._uow = uow

    async def execute(self, req: ComputeRestatementDeltaRequest) -> ComputeRestatementDeltaResult:
        """Execute restatement delta computation.

        Args:
            req: Parameters describing the target statement and version pair.

        Returns:
            A :class:`ComputeRestatementDeltaResult` containing both source
            versions and the computed restatement delta.

        Raises:
            EdgarMappingError:
                If request parameters are invalid (empty CIK, non-positive
                fiscal_year, invalid version sequences).
            EdgarIngestionError:
                If the requested statement versions cannot be found or if
                either version lacks a normalized payload.
        """
        cik = req.cik.strip()
        if not cik:
            raise EdgarMappingError("CIK must not be empty for compute_restatement_delta().")

        if req.fiscal_year <= 0:
            raise EdgarMappingError(
                "fiscal_year must be a positive integer for compute_restatement_delta().",
                details={"fiscal_year": req.fiscal_year},
            )

        if req.from_version_sequence <= 0 or req.to_version_sequence <= 0:
            raise EdgarMappingError(
                "Version sequences must be positive integers for compute_restatement_delta().",
                details={
                    "from_version_sequence": req.from_version_sequence,
                    "to_version_sequence": req.to_version_sequence,
                },
            )

        if req.from_version_sequence >= req.to_version_sequence:
            raise EdgarMappingError(
                "from_version_sequence must be strictly less than to_version_sequence.",
                details={
                    "from_version_sequence": req.from_version_sequence,
                    "to_version_sequence": req.to_version_sequence,
                },
            )

        logger.info(
            "edgar.compute_restatement_delta.start",
            extra={
                "cik": cik,
                "statement_type": req.statement_type.value,
                "fiscal_year": req.fiscal_year,
                "fiscal_period": req.fiscal_period.value,
                "from_version_sequence": req.from_version_sequence,
                "to_version_sequence": req.to_version_sequence,
                "metrics": [m.value for m in (req.metrics or ())],
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

        by_sequence: dict[int, EdgarStatementVersion] = {v.version_sequence: v for v in versions}

        from_version = by_sequence.get(req.from_version_sequence)
        to_version = by_sequence.get(req.to_version_sequence)

        if from_version is None or to_version is None:
            logger.info(
                "edgar.compute_restatement_delta.version_missing",
                extra={
                    "cik": cik,
                    "statement_type": req.statement_type.value,
                    "fiscal_year": req.fiscal_year,
                    "fiscal_period": req.fiscal_period.value,
                    "from_version_sequence": req.from_version_sequence,
                    "to_version_sequence": req.to_version_sequence,
                    "available_sequences": sorted(by_sequence.keys()),
                },
            )
            raise EdgarIngestionError(
                "Requested EDGAR statement versions not found for restatement delta.",
                details={
                    "cik": cik,
                    "statement_type": req.statement_type.value,
                    "fiscal_year": req.fiscal_year,
                    "fiscal_period": req.fiscal_period.value,
                    "from_version_sequence": req.from_version_sequence,
                    "to_version_sequence": req.to_version_sequence,
                    "available_sequences": sorted(by_sequence.keys()),
                },
            )

        if from_version.normalized_payload is None or to_version.normalized_payload is None:
            logger.warning(
                "edgar.compute_restatement_delta.missing_normalized_payload",
                extra={
                    "cik": cik,
                    "statement_type": req.statement_type.value,
                    "fiscal_year": req.fiscal_year,
                    "fiscal_period": req.fiscal_period.value,
                    "from_version_sequence": req.from_version_sequence,
                    "to_version_sequence": req.to_version_sequence,
                    "from_has_payload": from_version.normalized_payload is not None,
                    "to_has_payload": to_version.normalized_payload is not None,
                },
            )
            raise EdgarIngestionError(
                "Both statement versions must have normalized payloads for restatement delta.",
                details={
                    "cik": cik,
                    "statement_type": req.statement_type.value,
                    "fiscal_year": req.fiscal_year,
                    "fiscal_period": req.fiscal_period.value,
                    "from_version_sequence": req.from_version_sequence,
                    "to_version_sequence": req.to_version_sequence,
                },
            )

        delta = compute_restatement_delta(
            from_payload=from_version.normalized_payload,
            to_payload=to_version.normalized_payload,
            metrics=req.metrics,
        )

        logger.info(
            "edgar.compute_restatement_delta.success",
            extra={
                "cik": cik,
                "statement_type": req.statement_type.value,
                "statement_date": delta.statement_date.isoformat(),
                "fiscal_year": delta.fiscal_year,
                "fiscal_period": delta.fiscal_period.value,
                "from_version_sequence": delta.from_version_sequence,
                "to_version_sequence": delta.to_version_sequence,
                "changed_metrics": [m.value for m in delta.metrics],
            },
        )

        return ComputeRestatementDeltaResult(
            from_version=from_version,
            to_version=to_version,
            delta=delta,
        )


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
