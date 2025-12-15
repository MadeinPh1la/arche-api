# src/arche_api/application/services/persist_reconciliation_checks.py
# Copyright (c) Arche.
# SPDX-License-Identifier: MIT
"""Reconciliation ledger persistence service (application layer).

Purpose:
    Provide a small orchestration service that persists reconciliation results
    into the reconciliation ledger (E11-C) using UnitOfWork + repository ports.

Layer:
    application/services

Notes:
    - This service performs orchestration only:
        * No SQLAlchemy imports.
        * No HTTP concerns.
        * No commit/rollback; callers control transactions via UnitOfWork.
    - The repository is resolved via the domain interface key to preserve Clean
      Architecture boundaries.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from datetime import datetime

from arche_api.application.uow import UnitOfWork
from arche_api.domain.entities.edgar_reconciliation import ReconciliationResult
from arche_api.domain.interfaces.repositories.edgar_reconciliation_checks_repository import (
    EdgarReconciliationChecksRepository,
)


@dataclass(frozen=True, slots=True)
class ReconciliationRunContext:
    """Context metadata for a reconciliation run.

    Attributes:
        reconciliation_run_id:
            Stable identifier for the run. This SHOULD be a UUID string.
        executed_at:
            Timestamp at which the reconciliation run completed.
    """

    reconciliation_run_id: str
    executed_at: datetime


class PersistReconciliationChecksService:
    """Application service to persist reconciliation results into the ledger."""

    async def persist(
        self,
        *,
        uow: UnitOfWork,
        ctx: ReconciliationRunContext,
        results: Sequence[ReconciliationResult],
    ) -> None:
        """Persist reconciliation results into the reconciliation ledger.

        Args:
            uow:
                Active UnitOfWork providing the transactional scope and repository
                resolution.
            ctx:
                Reconciliation run context metadata.
            results:
                Collection of reconciliation results to persist.

        Raises:
            Exception:
                Any repository/domain exceptions are propagated; callers should
                wrap this in run_in_uow() or their use case error policy.
        """
        repo = uow.get_repository(EdgarReconciliationChecksRepository)
        await repo.append_results(
            reconciliation_run_id=ctx.reconciliation_run_id,
            executed_at=ctx.executed_at,
            results=results,
        )


__all__ = ["ReconciliationRunContext", "PersistReconciliationChecksService"]
