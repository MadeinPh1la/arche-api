# src/arche_api/domain/interfaces/repositories/edgar_reconciliation_checks_repository.py
# Copyright (c) Arche.
# SPDX-License-Identifier: MIT
"""EDGAR reconciliation ledger repository interface.

Purpose:
    Define persistence and query operations for reconciliation rule evaluation
    results produced by the EDGAR reconciliation engine (E11). This repository
    provides append-only access to the persistent reconciliation ledger.

Layer:
    domain/interfaces/repositories

Notes:
    Implementations live in the adapters/infrastructure layers (e.g.,
    SQLAlchemy repositories) and must translate DB/driver errors into domain
    exceptions where appropriate.

    Deterministic ordering is required for modeling workloads and reproducible
    reconciliation pipelines.
"""

from __future__ import annotations

from collections.abc import Sequence
from datetime import datetime
from typing import Protocol

from arche_api.domain.entities.edgar_dq import NormalizedStatementIdentity
from arche_api.domain.entities.edgar_reconciliation import ReconciliationResult


class EdgarReconciliationChecksRepository(Protocol):
    """Protocol for repositories managing EDGAR reconciliation ledger checks."""

    async def append_results(
        self,
        *,
        reconciliation_run_id: str,
        executed_at: datetime,
        results: Sequence[ReconciliationResult],
    ) -> None:
        """Append reconciliation results to the persistent ledger.

        Implementations must:
            - Persist results as append-only ledger entries (no destructive
              overwrite).
            - Preserve deterministic identity and ordering guarantees for later
              query workloads.
            - Enforce a stable uniqueness model at minimum within a run
              (e.g., rule_id + dimension_key + statement identity within the
              reconciliation_run_id).

        Args:
            reconciliation_run_id:
                Stable identifier for the reconciliation run. This SHOULD be a
                UUID string in canonical form.
            executed_at:
                Timestamp at which the reconciliation run completed.
            results:
                Collection of reconciliation results to append to the ledger.
        """

    async def list_for_statement(
        self,
        *,
        identity: NormalizedStatementIdentity,
        reconciliation_run_id: str | None = None,
        limit: int | None = None,
    ) -> Sequence[ReconciliationResult]:
        """Return reconciliation ledger entries for a given statement identity.

        Args:
            identity:
                Normalized statement identity (including version_sequence).
            reconciliation_run_id:
                Optional run identifier to restrict results to a single run.
                When None, returns results across all runs for the statement.
            limit:
                Optional limit applied after deterministic ordering.

        Returns:
            A deterministically ordered sequence of reconciliation results.
            Implementations SHOULD document the ordering, for example:

                - executed_at ASC
                - rule_category ASC
                - rule_id ASC
                - dimension_key ASC NULLS LAST
                - check_id ASC
        """

    async def list_for_window(
        self,
        *,
        cik: str,
        statement_type: str,
        fiscal_year_from: int,
        fiscal_year_to: int,
        limit: int = 5000,
    ) -> Sequence[ReconciliationResult]:
        """Return reconciliation ledger entries across a multi-period window.

        This method is intended for modeling workloads and reconciliation
        reporting that needs a deterministic time-series slice.

        Args:
            cik:
                Company CIK.
            statement_type:
                Statement type code (matching StatementType.value).
            fiscal_year_from:
                Inclusive start fiscal year.
            fiscal_year_to:
                Inclusive end fiscal year.
            limit:
                Maximum number of rows to return.

        Returns:
            A deterministically ordered sequence of reconciliation results.
            Implementations SHOULD order by fiscal period timeline keys first,
            then rule identity keys, for example:

                - fiscal_year ASC
                - fiscal_period ASC
                - version_sequence ASC
                - executed_at ASC
                - rule_category ASC
                - rule_id ASC
                - dimension_key ASC NULLS LAST
                - check_id ASC
        """


__all__ = ["EdgarReconciliationChecksRepository"]
