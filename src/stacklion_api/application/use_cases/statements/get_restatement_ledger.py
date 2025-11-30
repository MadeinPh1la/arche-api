# src/stacklion_api/application/use_cases/statements/get_restatement_ledger.py
# Copyright (c)
# SPDX-License-Identifier: MIT
"""Use case: Build a restatement ledger for a statement identity.

Purpose:
    For a given (cik, statement_type, fiscal_year, fiscal_period) identity,
    load all statement versions, run the domain ledger engine, and project the
    results into application-level DTOs suitable for HTTP presentation.

Layer:
    application

Notes:
    - Read-only use case; depends on the EDGAR statements repository via the
      UnitOfWork abstraction.
    - Delegates ledger construction to the domain-level
      ``build_restatement_ledger`` helper.
    - Surface-only application concerns here (logging, DTO mapping, validation).
"""

from __future__ import annotations

import logging
from collections.abc import Sequence
from dataclasses import dataclass
from typing import Any, cast

from stacklion_api.application.schemas.dto.edgar import (
    RestatementLedgerDTO,
    RestatementLedgerEntryDTO,
    RestatementSummaryDTO,
)
from stacklion_api.application.uow import UnitOfWork
from stacklion_api.domain.entities.edgar_restatement_delta import RestatementDelta
from stacklion_api.domain.entities.edgar_statement_version import EdgarStatementVersion
from stacklion_api.domain.enums.edgar import FiscalPeriod, StatementType
from stacklion_api.domain.exceptions.edgar import EdgarIngestionError, EdgarMappingError
from stacklion_api.domain.interfaces.repositories.edgar_statements_repository import (
    EdgarStatementsRepository as EdgarStatementsRepositoryProtocol,
)
from stacklion_api.domain.services.statement_ledger_delta_engine import (
    build_restatement_ledger,
)

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class GetRestatementLedgerRequest:
    """Request parameters for restatement ledger construction.

    Attributes:
        cik:
            Central Index Key for the filer.
        statement_type:
            Statement type (income, balance sheet, cash flow, etc.).
        fiscal_year:
            Fiscal year associated with the statement.
        fiscal_period:
            Fiscal period within the year (e.g., FY, Q1, Q2).
    """

    cik: str
    statement_type: StatementType
    fiscal_year: int
    fiscal_period: FiscalPeriod


class GetRestatementLedgerUseCase:
    """Build a restatement ledger for a specific statement identity.

    This use case loads all EDGAR statement versions for a given
    (cik, statement_type, fiscal_year, fiscal_period) identity,
    delegates ledger construction to the domain statement ledger
    engine, and returns an application-level DTO projection.

    Args:
        uow:
            Application :class:`UnitOfWork` abstraction used to resolve
            the EDGAR statements repository.

    Returns:
        Instances of this use case return a
        :class:`RestatementLedgerDTO` when :meth:`execute` is called.

    Raises:
        EdgarMappingError:
            If request parameters are invalid (for example, empty CIK or
            non-positive fiscal_year).
        EdgarIngestionError:
            If no statement versions exist or there are fewer than two
            normalized versions available to build a ledger.
    """

    def __init__(self, uow: UnitOfWork) -> None:
        """Initialize the use case.

        Args:
            uow: Application UnitOfWork abstraction used to resolve repositories.
        """
        self._uow = uow

    async def execute(self, req: GetRestatementLedgerRequest) -> RestatementLedgerDTO:
        """Execute restatement ledger construction.

        Args:
            req: Parameters describing the target statement identity.

        Returns:
            A :class:`RestatementLedgerDTO` representing the full ledger for the
            requested identity.

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
            raise EdgarMappingError("CIK must not be empty for get_restatement_ledger().")

        if req.fiscal_year <= 0:
            raise EdgarMappingError(
                "fiscal_year must be a positive integer for get_restatement_ledger().",
                details={"fiscal_year": req.fiscal_year},
            )

        logger.info(
            "edgar.get_restatement_ledger.start",
            extra={
                "cik": cik,
                "statement_type": req.statement_type.value,
                "fiscal_year": req.fiscal_year,
                "fiscal_period": req.fiscal_period.value,
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
                "No EDGAR statement versions found for restatement ledger.",
                details={
                    "cik": cik,
                    "statement_type": req.statement_type.value,
                    "fiscal_year": req.fiscal_year,
                    "fiscal_period": req.fiscal_period.value,
                },
            )

        _ensure_minimum_normalized_versions(versions, cik, req)

        deltas: list[RestatementDelta] = build_restatement_ledger(versions=versions)

        # Build DTO entries. Ordering should already be by version_sequence ASC
        # in the domain engine, but we enforce determinism here as well.
        entries: list[RestatementLedgerEntryDTO] = []
        for delta in sorted(
            deltas,
            key=lambda d: (d.from_version_sequence, d.to_version_sequence),
        ):
            summary_dto = _build_summary_from_delta(delta)
            entries.append(
                RestatementLedgerEntryDTO(
                    from_version_sequence=delta.from_version_sequence,
                    to_version_sequence=delta.to_version_sequence,
                    summary=summary_dto,
                    # Metric-level deltas are currently not surfaced at the
                    # ledger hop level; this field is required by the DTO and
                    # will be populated when the domain engine exposes them.
                    deltas=[],
                ),
            )

        if not entries:
            # This should only occur if the domain engine produced no deltas
            # despite having sufficient normalized versions.
            raise EdgarIngestionError(
                "Failed to construct restatement ledger; no deltas produced.",
                details={
                    "cik": cik,
                    "statement_type": req.statement_type.value,
                    "fiscal_year": req.fiscal_year,
                    "fiscal_period": req.fiscal_period.value,
                },
            )

        ledger_dto = RestatementLedgerDTO(
            cik=cik,
            statement_type=req.statement_type,
            fiscal_year=req.fiscal_year,
            fiscal_period=req.fiscal_period,
            entries=entries,
        )

        logger.info(
            "edgar.get_restatement_ledger.success",
            extra={
                "cik": cik,
                "statement_type": req.statement_type.value,
                "fiscal_year": req.fiscal_year,
                "fiscal_period": req.fiscal_period.value,
                "entries": len(entries),
                "first_from_version_sequence": entries[0].from_version_sequence,
                "last_to_version_sequence": entries[-1].to_version_sequence,
            },
        )

        return ledger_dto


def _ensure_minimum_normalized_versions(
    versions: Sequence[EdgarStatementVersion],
    cik: str,
    req: GetRestatementLedgerRequest,
) -> None:
    """Ensure there are at least two normalized versions available.

    The domain ledger engine will happily return an empty list when fewer than
    two normalized payloads are present. At the use-case boundary we choose to
    surface this as an ingestion error to callers.
    """
    normalized_versions = [v for v in versions if v.normalized_payload is not None]
    if len(normalized_versions) < 2:
        raise EdgarIngestionError(
            "At least two normalized EDGAR statement versions are required to "
            "build a restatement ledger.",
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
    """Build a high-level summary DTO from a RestatementDelta.

    Notes:
        The domain object does not currently expose the full set of metrics
        considered (including unchanged ones). For now, we treat the set of
        changed metrics as the set of "compared" metrics. This keeps the
        summary deterministic and can be refined later without breaking the
        DTO contract.
    """
    total_metrics_changed = len(delta.metrics)
    total_metrics_compared = total_metrics_changed
    has_material_change = total_metrics_changed > 0

    return RestatementSummaryDTO(
        total_metrics_compared=total_metrics_compared,
        total_metrics_changed=total_metrics_changed,
        has_material_change=has_material_change,
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
