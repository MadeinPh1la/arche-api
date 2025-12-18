# Copyright (c)
# SPDX-License-Identifier: MIT
"""Use case: Read reconciliation ledger for a statement identity.

Purpose:
    Provide deterministic ledger reads for a specific normalized statement identity,
    with optional filtering by rule category and statuses.

Layer:
    application/use_cases/reconciliation
"""

from __future__ import annotations

from typing import Any, cast

from arche_api.application.schemas.dto.reconciliation import (
    GetReconciliationLedgerRequestDTO,
    GetReconciliationLedgerResponseDTO,
    ReconciliationLedgerEntryDTO,
    ReconciliationResultDTO,
)
from arche_api.application.uow import UnitOfWork
from arche_api.domain.entities.edgar_reconciliation import ReconciliationResult
from arche_api.domain.enums.edgar_reconciliation import (
    ReconciliationRuleCategory,
    ReconciliationStatus,
)
from arche_api.domain.interfaces.repositories.edgar_reconciliation_checks_repository import (
    EdgarReconciliationChecksRepository as EdgarReconciliationChecksRepositoryPort,
)


class GetReconciliationLedgerUseCase:
    """Read reconciliation checks from the persistent ledger.

    Args:
        uow: Application UnitOfWork used to resolve the ledger repository.

    Raises:
        Exception: Propagates unexpected persistence failures from lower layers.
    """

    def __init__(self, *, uow: UnitOfWork) -> None:
        """Initialize the use case.

        Args:
            uow: Application UnitOfWork used for repository resolution and transaction scope.
        """
        self._uow = uow

    async def execute(
        self, req: GetReconciliationLedgerRequestDTO
    ) -> GetReconciliationLedgerResponseDTO:
        """Execute the ledger read.

        Args:
            req: Request DTO including statement identity and optional filters.

        Returns:
            Response DTO containing the identity and deterministically ordered ledger entries.
        """
        async with self._uow as tx:
            repo = _get_repo(tx)
            results = await repo.list_for_statement(
                identity=req.identity,
                reconciliation_run_id=req.reconciliation_run_id,
                limit=req.limit,
            )

        filtered = _apply_filters(
            results=results,
            rule_category=req.rule_category,
            statuses=req.statuses,
        )

        items = tuple(
            ReconciliationLedgerEntryDTO(
                executed_at=None,  # Ledger storage may carry executed_at; domain results do not.
                result=_map_result(r),
            )
            for r in filtered
        )

        return GetReconciliationLedgerResponseDTO(identity=req.identity, items=items)


def _get_repo(tx: Any) -> EdgarReconciliationChecksRepositoryPort:
    """Resolve the reconciliation checks repository from a UnitOfWork/transaction.

    Args:
        tx: Active UnitOfWork transaction context (real or test double).

    Returns:
        Repository port for reconciliation checks.
    """
    if hasattr(tx, "reconciliation_checks_repo"):
        return cast(EdgarReconciliationChecksRepositoryPort, tx.reconciliation_checks_repo)
    repo_any = tx.get_repository(EdgarReconciliationChecksRepositoryPort)
    return cast(EdgarReconciliationChecksRepositoryPort, repo_any)


def _apply_filters(
    *,
    results: list[ReconciliationResult] | tuple[ReconciliationResult, ...] | Any,
    rule_category: ReconciliationRuleCategory | None,
    statuses: tuple[ReconciliationStatus, ...] | None,
) -> tuple[ReconciliationResult, ...]:
    """Apply in-memory filters to a sequence of reconciliation results.

    Args:
        results: Ledger results from the repository (list/tuple compatible).
        rule_category: Optional rule category to include.
        statuses: Optional set of statuses to include.

    Returns:
        Filtered results as a tuple in the same stable order as the input.
    """
    items = list(results)
    if rule_category is not None:
        items = [r for r in items if r.rule_category == rule_category]
    if statuses is not None:
        status_set = set(statuses)
        items = [r for r in items if r.status in status_set]
    return tuple(items)


def _map_result(r: ReconciliationResult) -> ReconciliationResultDTO:
    """Map a domain ReconciliationResult to an application DTO.

    Args:
        r: Domain reconciliation result.

    Returns:
        Application DTO representation.
    """
    return ReconciliationResultDTO(
        statement_identity=r.statement_identity,
        rule_id=r.rule_id,
        rule_category=r.rule_category,
        status=r.status,
        severity=str(r.severity),
        expected_value=r.expected_value,
        actual_value=r.actual_value,
        delta=r.delta,
        dimension_key=r.dimension_key,
        dimension_labels=r.dimension_labels,
        notes=r.notes,
    )
