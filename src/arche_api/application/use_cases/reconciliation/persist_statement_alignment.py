# src/arche_api/application/use_cases/reconciliation/persist_statement_alignment.py
# Copyright (c)
# SPDX-License-Identifier: MIT
"""Persist EDGAR statement alignment results.

Purpose:
    Bridge the reconciliation stitching engine (E11) and the
    `sec.edgar_statement_alignment` persistence layer by mapping stitching
    outputs into alignment records and storing them via the UnitOfWork.

Layer:
    application/use_cases

Notes:
    - This use case is intentionally thin: all business logic around
      stitching/calendar inference lives in the domain layer. The use case
      only:
        * Enters a UnitOfWork context.
        * Resolves the alignment repository port.
        * Persists the provided alignment records.
        * Commits on success.
"""

from __future__ import annotations

from collections.abc import Sequence
from typing import cast

from arche_api.application.uow import UnitOfWork
from arche_api.domain.interfaces.repositories.edgar_statement_alignment_repository import (
    EdgarStatementAlignmentRepository as EdgarStatementAlignmentRepositoryPort,
)
from arche_api.domain.interfaces.repositories.edgar_statement_alignment_repository import (
    StatementAlignmentRecord,
)


class PersistStatementAlignmentUseCase:
    """Use case for persisting EDGAR statement alignment results.

    This use case is called after the reconciliation/stitching engine
    has produced a set of alignment records for one or more statements.
    It persists those records into `sec.edgar_statement_alignment`
    using the configured UnitOfWork and repository wiring.

    Args:
        uow:
            UnitOfWork instance implementing the application-layer
            UnitOfWork protocol and async context manager semantics.
            The use case will enter this UnitOfWork via
            ``async with uow as tx:`` when executing.
        alignment_repo_type:
            Repository interface key used with ``uow.get_repository(...)``
            to resolve the alignment repository. This defaults to the
            domain-level port ``EdgarStatementAlignmentRepositoryPort``
            and typically should not be overridden outside tests.

    Attributes:
        _uow:
            Stored UnitOfWork instance used to open transactional scopes.
        _alignment_repo_type:
            Repository key used to resolve the alignment repository.

    Returns:
        PersistStatementAlignmentUseCase:
            A new use case instance configured with the provided UnitOfWork
            and repository key.
    """

    def __init__(
        self,
        *,
        uow: UnitOfWork,
        alignment_repo_type: type[EdgarStatementAlignmentRepositoryPort] | type = (
            EdgarStatementAlignmentRepositoryPort
        ),
    ) -> None:
        """Initialize the use case with its UnitOfWork and repository type."""
        self._uow = uow
        self._alignment_repo_type = alignment_repo_type

    async def execute(self, *, results: Sequence[StatementAlignmentRecord]) -> None:
        """Persist a batch of statement alignment records.

        This method is intentionally idempotent with respect to alignment
        identity: the underlying repository is responsible for performing
        an upsert keyed by statement version / identity.

        Args:
            results:
                Sequence of alignment records to persist. These records are
                typically produced by the reconciliation stitching engine and
                conform to the ``StatementAlignmentRecord`` protocol.

        Returns:
            None. On success, all provided records are persisted and the
            UnitOfWork is committed.

        Raises:
            arche_api.domain.exceptions.edgar.EdgarError:
                If the repository reports ingestion/persistence failures.
            Exception:
                Any unexpected exception will propagate after the UnitOfWork
                attempts a rollback.
        """
        if not results:
            # No-op to avoid opening a transaction for empty input.
            return

        async with self._uow as uow_instance:
            repo_any = uow_instance.get_repository(self._alignment_repo_type)
            repo = cast(EdgarStatementAlignmentRepositoryPort, repo_any)

            await repo.upsert_alignments(results)
            # No explicit commit() call here; commit is handled by __aexit__.
