# tests/unit/application/use_cases/statements/test_persist_normalized_facts_for_statement.py
# Copyright (c)
# SPDX-License-Identifier: MIT
"""Tests for PersistNormalizedFactsForStatementUseCase."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import date
from decimal import Decimal
from typing import Any

import pytest

from arche_api.application.schemas.dto.edgar_dq import (
    PersistNormalizedFactsResultDTO,
)
from arche_api.application.uow import UnitOfWork
from arche_api.application.use_cases.statements.persist_normalized_facts_for_statement import (
    PersistNormalizedFactsForStatementRequest,
    PersistNormalizedFactsForStatementUseCase,
)
from arche_api.domain.enums.canonical_statement_metric import CanonicalStatementMetric
from arche_api.domain.enums.edgar import AccountingStandard, FiscalPeriod, StatementType
from arche_api.domain.exceptions.edgar import EdgarIngestionError

# --------------------------------------------------------------------------- #
# Fakes                                                                       #
# --------------------------------------------------------------------------- #


@dataclass(slots=True)
class _FakeCanonicalPayload:
    cik: str
    statement_type: StatementType
    accounting_standard: AccountingStandard
    statement_date: date
    fiscal_year: int
    fiscal_period: FiscalPeriod
    currency: str
    unit_multiplier: int
    core_metrics: Mapping[CanonicalStatementMetric, Decimal]
    extra_metrics: Mapping[str, Decimal]
    dimensions: Mapping[str, str]
    source_accession_id: str
    source_taxonomy: str
    source_version_sequence: int


@dataclass(slots=True)
class _FakeStatementVersion:
    cik: str
    statement_type: StatementType
    fiscal_year: int
    fiscal_period: FiscalPeriod
    version_sequence: int
    normalized_payload: _FakeCanonicalPayload | None


class _FakeStatementsRepository:
    """Fake statements repo returning a single version matching the identity."""

    def __init__(self, versions: Sequence[_FakeStatementVersion]) -> None:
        self._versions = list(versions)

    async def list_statement_versions_for_company(
        self,
        *,
        cik: str,
        statement_type: StatementType,
        fiscal_year: int,
        fiscal_period: FiscalPeriod | None = None,
    ) -> Sequence[_FakeStatementVersion]:
        return [
            v
            for v in self._versions
            if v.cik == cik
            and v.statement_type == statement_type
            and v.fiscal_year == fiscal_year
            and (fiscal_period is None or v.fiscal_period == fiscal_period)
        ]


class _CapturedFactsRepository:
    """Fake facts repo that captures the last replace_facts_for_statement call."""

    def __init__(self) -> None:
        self.last_identity: Any | None = None
        self.last_facts: list[Any] = []

    async def replace_facts_for_statement(self, *, identity: Any, facts: Sequence[Any]) -> None:
        self.last_identity = identity
        self.last_facts = list(facts)


class _FakeUnitOfWork(UnitOfWork):
    """Minimal in-memory UnitOfWork implementation for tests."""

    def __init__(self, statements_repo: Any, facts_repo: Any) -> None:
        self._statements_repo = statements_repo
        self._facts_repo = facts_repo
        self._committed = False

    async def __aenter__(self) -> _FakeUnitOfWork:  # type: ignore[override]
        return self

    async def __aexit__(self, exc_type, exc, tb) -> bool | None:  # type: ignore[override]
        return None

    async def commit(self) -> None:  # type: ignore[override]
        self._committed = True

    async def rollback(self) -> None:  # type: ignore[override]
        pass

    def get_repository(self, repo_type: type[Any]) -> Any:  # type: ignore[override]
        # The use-case resolves by protocol type; we just match on name.
        if "Statements" in repo_type.__name__:
            return self._statements_repo
        if "Facts" in repo_type.__name__:
            return self._facts_repo
        raise KeyError(repo_type)


# --------------------------------------------------------------------------- #
# Tests                                                                       #
# --------------------------------------------------------------------------- #


@pytest.mark.asyncio
async def test_persist_normalized_facts_happy_path() -> None:
    cik = "0000123456"
    payload = _FakeCanonicalPayload(
        cik=cik,
        statement_type=StatementType.INCOME_STATEMENT,
        accounting_standard=AccountingStandard.US_GAAP,
        statement_date=date(2024, 3, 31),
        fiscal_year=2024,
        fiscal_period=FiscalPeriod.Q1,
        currency="USD",
        unit_multiplier=0,
        core_metrics={CanonicalStatementMetric.REVENUE: Decimal("100.00")},
        extra_metrics={"CUSTOM_METRIC": Decimal("5.00")},
        dimensions={"segment": "US"},
        source_accession_id="0000123456-24-000001",
        source_taxonomy="US_GAAP_2024",
        source_version_sequence=1,
    )
    statement = _FakeStatementVersion(
        cik=cik,
        statement_type=payload.statement_type,
        fiscal_year=payload.fiscal_year,
        fiscal_period=payload.fiscal_period,
        version_sequence=1,
        normalized_payload=payload,
    )

    statements_repo = _FakeStatementsRepository([statement])
    facts_repo = _CapturedFactsRepository()
    uow = _FakeUnitOfWork(statements_repo, facts_repo)

    use_case = PersistNormalizedFactsForStatementUseCase(uow=uow)

    req = PersistNormalizedFactsForStatementRequest(
        cik=cik,
        statement_type=payload.statement_type,
        fiscal_year=payload.fiscal_year,
        fiscal_period=payload.fiscal_period,
        version_sequence=1,
    )

    result = await use_case.execute(req)

    assert isinstance(result, PersistNormalizedFactsResultDTO)
    assert result.cik == cik
    assert result.facts_persisted == 2  # REVENUE + CUSTOM_METRIC

    # Facts actually passed to repo
    assert facts_repo.last_identity is not None
    assert len(facts_repo.last_facts) == 2
    metric_codes = sorted(f.metric_code for f in facts_repo.last_facts)
    assert metric_codes == ["CUSTOM_METRIC", CanonicalStatementMetric.REVENUE.value]


@pytest.mark.asyncio
async def test_persist_normalized_facts_raises_if_no_payload() -> None:
    cik = "0000123456"
    statement = _FakeStatementVersion(
        cik=cik,
        statement_type=StatementType.INCOME_STATEMENT,
        fiscal_year=2024,
        fiscal_period=FiscalPeriod.Q1,
        version_sequence=1,
        normalized_payload=None,
    )

    statements_repo = _FakeStatementsRepository([statement])
    facts_repo = _CapturedFactsRepository()
    uow = _FakeUnitOfWork(statements_repo, facts_repo)

    use_case = PersistNormalizedFactsForStatementUseCase(uow=uow)

    req = PersistNormalizedFactsForStatementRequest(
        cik=cik,
        statement_type=StatementType.INCOME_STATEMENT,
        fiscal_year=2024,
        fiscal_period=FiscalPeriod.Q1,
        version_sequence=1,
    )

    with pytest.raises(EdgarIngestionError) as excinfo:
        await use_case.execute(req)

    msg = str(excinfo.value)
    assert "normalized payload" in msg or "normalized" in msg.lower()
