# tests/unit/application/use_cases/test_persist_statement_alignment.py
# Copyright (c)
# SPDX-License-Identifier: MIT
"""Unit tests for PersistStatementAlignmentUseCase.

These tests focus on basic conventions (docstring, execute method) and a
smoke test for wiring the UnitOfWork dependency.
"""

from __future__ import annotations

from collections.abc import Sequence
from typing import Any

import pytest

from arche_api.application.use_cases.reconciliation.persist_statement_alignment import (
    PersistStatementAlignmentUseCase,
)
from arche_api.domain.entities.edgar_reconciliation import StatementAlignmentResult
from arche_api.domain.interfaces.repositories.edgar_statement_alignment_repository import (
    EdgarStatementAlignmentRepository as EdgarStatementAlignmentRepositoryPort,
)


class _FakeAlignmentRepository(EdgarStatementAlignmentRepositoryPort):
    """Minimal fake alignment repository for use case testing."""

    def __init__(self) -> None:
        self.upserted: list[Any] = []

    async def upsert_alignment(self, record: Any) -> None:  # type: ignore[override]
        self.upserted.append(record)

    async def upsert_alignments(self, records: Sequence[Any]) -> None:  # type: ignore[override]
        self.upserted.extend(records)

    async def get_alignment_for_statement(self, *args: Any, **kwargs: Any) -> Any:  # type: ignore[override]
        return None

    async def list_alignment_timeline_for_company(self, *args: Any, **kwargs: Any) -> Sequence[Any]:  # type: ignore[override]
        return []


class _FakeUoW:
    """Fake UnitOfWork that returns the fake alignment repository."""

    def __init__(self) -> None:
        self.repo = _FakeAlignmentRepository()
        self.committed = False

    async def __aenter__(self) -> _FakeUoW:
        return self

    async def __aexit__(self, exc_type, exc, tb) -> None:
        if exc is None:
            self.committed = True

    def get_repository(self, repo_type: Any) -> Any:
        if repo_type is EdgarStatementAlignmentRepositoryPort:
            return self.repo
        msg = f"Unexpected repository requested: {repo_type!r}"
        raise AssertionError(msg)


def test_use_case_has_google_style_docstring_and_execute() -> None:
    """PersistStatementAlignmentUseCase must expose execute() and docstring."""
    doc = PersistStatementAlignmentUseCase.__doc__ or ""
    assert "Args:" in doc
    assert "Returns:" in doc
    assert hasattr(PersistStatementAlignmentUseCase, "execute")
    assert callable(PersistStatementAlignmentUseCase.execute)


@pytest.mark.anyio
async def test_execute_persists_alignment_results_via_uow() -> None:
    """execute() must delegate alignment persistence through the UnitOfWork."""
    uow = _FakeUoW()
    use_case = PersistStatementAlignmentUseCase(uow=uow)

    # Minimal fake alignment result; only attributes used by the use case
    # need to be populated in real-world tests.
    fake_result = StatementAlignmentResult(
        cik="0000000000",
        statement_type="INCOME_STATEMENT",
        fiscal_year=2023,
        fiscal_period="FY",
        statement_date=None,
        version_sequence=1,
        details={},
    )

    await use_case.execute(results=[fake_result])

    assert uow.committed is True
    assert len(uow.repo.upserted) == 1
