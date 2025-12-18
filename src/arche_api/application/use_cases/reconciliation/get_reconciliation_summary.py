# Copyright (c)
# SPDX-License-Identifier: MIT
"""Use case: Reconciliation summary over a multi-year window.

Purpose:
    Aggregate reconciliation ledger entries into summary buckets grouped by:
        (fiscal_year, fiscal_period, version_sequence, rule_category).

Layer:
    application/use_cases/reconciliation
"""

from __future__ import annotations

from collections import defaultdict
from typing import Any, cast

from arche_api.application.schemas.dto.reconciliation import (
    GetReconciliationSummaryRequestDTO,
    GetReconciliationSummaryResponseDTO,
    ReconciliationSummaryBucketDTO,
)
from arche_api.application.uow import UnitOfWork
from arche_api.domain.enums.edgar_reconciliation import ReconciliationRuleCategory
from arche_api.domain.interfaces.repositories.edgar_reconciliation_checks_repository import (
    EdgarReconciliationChecksRepository as EdgarReconciliationChecksRepositoryPort,
)


class GetReconciliationSummaryUseCase:
    """Aggregate reconciliation ledger entries into summary buckets.

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
        self, req: GetReconciliationSummaryRequestDTO
    ) -> GetReconciliationSummaryResponseDTO:
        """Execute the summary aggregation.

        Args:
            req: Request DTO describing the company, statement type, year window, and filters.

        Returns:
            Response DTO containing the summary buckets.
        """
        async with self._uow as tx:
            repo = _get_repo(tx)
            rows = await repo.list_for_window(
                cik=req.cik,
                statement_type=req.statement_type,
                fiscal_year_from=req.fiscal_year_from,
                fiscal_year_to=req.fiscal_year_to,
                limit=req.limit,
            )

        # Bucket key: (fy, fp, vs, category)
        counts: dict[tuple[int, str, int, ReconciliationRuleCategory], dict[str, int]] = (
            defaultdict(lambda: {"PASS": 0, "WARNING": 0, "FAIL": 0})
        )

        for r in rows:
            if req.rule_category is not None and r.rule_category != req.rule_category:
                continue

            key = (
                r.statement_identity.fiscal_year,
                r.statement_identity.fiscal_period.value,
                r.statement_identity.version_sequence,
                r.rule_category,
            )

            # r.status.value is expected to be one of: PASS / WARNING / FAIL
            counts[key][r.status.value] += 1

        buckets = [
            ReconciliationSummaryBucketDTO(
                fiscal_year=fy,
                fiscal_period=fp,
                version_sequence=vs,
                rule_category=cat,
                pass_count=v["PASS"],
                warn_count=v["WARNING"],
                fail_count=v["FAIL"],
            )
            for (fy, fp, vs, cat), v in counts.items()
        ]
        buckets.sort(
            key=lambda b: (
                b.fiscal_year,
                b.fiscal_period,
                b.version_sequence,
                b.rule_category.value,
            )
        )

        return GetReconciliationSummaryResponseDTO(
            cik=req.cik,
            statement_type=req.statement_type,
            fiscal_year_from=req.fiscal_year_from,
            fiscal_year_to=req.fiscal_year_to,
            buckets=tuple(buckets),
        )


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
