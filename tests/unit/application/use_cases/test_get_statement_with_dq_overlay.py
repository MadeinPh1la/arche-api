# tests/unit/application/use_cases/statements/test_get_statement_with_dq_overlay.py
# Copyright (c)
# SPDX-License-Identifier: MIT
"""Tests for GetStatementWithDQOverlayUseCase."""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from datetime import UTC, date, datetime
from typing import Any

import pytest

from stacklion_api.application.schemas.dto.edgar_dq import StatementDQOverlayDTO
from stacklion_api.application.uow import UnitOfWork
from stacklion_api.application.use_cases.statements.get_statement_with_dq_overlay import (
    GetStatementWithDQOverlayRequest,
    GetStatementWithDQOverlayUseCase,
)
from stacklion_api.domain.enums.edgar import (
    AccountingStandard,
    FiscalPeriod,
    MaterialityClass,
    StatementType,
)
from stacklion_api.domain.exceptions.edgar import EdgarIngestionError

# --------------------------------------------------------------------------- #
# Fakes                                                                       #
# --------------------------------------------------------------------------- #


@dataclass(slots=True)
class _FakeStatement:
    cik: str
    statement_type: StatementType
    fiscal_year: int
    fiscal_period: FiscalPeriod
    version_sequence: int
    accounting_standard: AccountingStandard
    statement_date: date
    currency: str


@dataclass(slots=True)
class _FakeStatementIdentity:
    cik: str
    statement_type: StatementType
    fiscal_year: int
    fiscal_period: FiscalPeriod
    version_sequence: int


@dataclass(slots=True)
class _FakeFact:
    cik: str
    statement_type: StatementType
    accounting_standard: AccountingStandard
    fiscal_year: int
    fiscal_period: FiscalPeriod
    statement_date: date
    version_sequence: int
    metric_code: str
    metric_label: str | None
    unit: str
    period_start: date | None
    period_end: date
    value: int
    dimension_key: str
    dimensions: dict[str, str]
    source_line_item: str | None


@dataclass(slots=True)
class _FakeFactQuality:
    dq_run_id: str
    statement_identity: _FakeStatementIdentity
    metric_code: str
    dimension_key: str
    severity: MaterialityClass
    is_present: bool
    is_non_negative: bool | None
    is_consistent_with_history: bool | None
    has_known_issue: bool
    details: dict[str, Any] | None


@dataclass(slots=True)
class _FakeAnomaly:
    dq_run_id: str
    metric_code: str | None
    dimension_key: str | None
    rule_code: str
    severity: MaterialityClass
    message: str
    details: dict[str, Any] | None


@dataclass(slots=True)
class _FakeDQRun:
    dq_run_id: str
    rule_set_version: str
    executed_at: datetime


class _FakeStatementsRepository:
    def __init__(self, statements: Sequence[_FakeStatement]) -> None:
        self._statements = list(statements)

    async def list_statement_versions_for_company(
        self,
        *,
        cik: str,
        statement_type: StatementType,
        fiscal_year: int,
        fiscal_period: FiscalPeriod | None = None,
    ) -> Sequence[_FakeStatement]:
        return [
            s
            for s in self._statements
            if s.cik == cik
            and s.statement_type == statement_type
            and s.fiscal_year == fiscal_year
            and (fiscal_period is None or s.fiscal_period == fiscal_period)
        ]


class _FakeFactsRepository:
    def __init__(self, facts: Sequence[_FakeFact]) -> None:
        self._facts = list(facts)

    async def list_facts_for_statement(
        self, *, identity: Any
    ) -> Sequence[_FakeFact]:  # noqa: ARG002
        return list(self._facts)


class _FakeDQRepository:
    def __init__(
        self,
        *,
        dq_run: _FakeDQRun | None,
        fact_quality: Sequence[_FakeFactQuality],
        anomalies: Sequence[_FakeAnomaly],
    ) -> None:
        self._dq_run = dq_run
        self._fact_quality = list(fact_quality)
        self._anomalies = list(anomalies)

    async def latest_run_for_statement(self, *, identity: Any) -> _FakeDQRun | None:  # noqa: ARG002
        return self._dq_run

    async def list_fact_quality_for_statement(
        self,
        *,
        identity: Any,  # noqa: ARG002
    ) -> list[_FakeFactQuality]:
        return list(self._fact_quality)

    async def list_anomalies_for_statement(
        self,
        *,
        identity: Any,  # noqa: ARG002
    ) -> list[_FakeAnomaly]:
        return list(self._anomalies)


class _FakeUnitOfWork(UnitOfWork):
    def __init__(
        self,
        statements_repo: Any,
        facts_repo: Any,
        dq_repo: Any,
    ) -> None:
        self._statements_repo = statements_repo
        self._facts_repo = facts_repo
        self._dq_repo = dq_repo

    async def __aenter__(self) -> _FakeUnitOfWork:  # type: ignore[override]
        return self

    async def __aexit__(self, exc_type, exc, tb) -> bool | None:  # type: ignore[override]
        return None

    async def commit(self) -> None:  # type: ignore[override]
        pass

    async def rollback(self) -> None:  # type: ignore[override]
        pass

    def get_repository(self, repo_type: type[Any]) -> Any:  # type: ignore[override]
        name = repo_type.__name__
        if "Statements" in name:
            return self._statements_repo
        if "Facts" in name:
            return self._facts_repo
        if "DQ" in name:
            return self._dq_repo
        raise KeyError(repo_type)


# --------------------------------------------------------------------------- #
# Tests                                                                       #
# --------------------------------------------------------------------------- #


@pytest.mark.asyncio
async def test_get_statement_with_dq_overlay_happy_path() -> None:
    cik = "0000123456"
    statement = _FakeStatement(
        cik=cik,
        statement_type=StatementType.INCOME_STATEMENT,
        fiscal_year=2024,
        fiscal_period=FiscalPeriod.Q1,
        version_sequence=2,
        accounting_standard=AccountingStandard.US_GAAP,
        statement_date=date(2024, 3, 31),
        currency="USD",
    )

    fact = _FakeFact(
        cik=cik,
        statement_type=statement.statement_type,
        accounting_standard=statement.accounting_standard,
        fiscal_year=statement.fiscal_year,
        fiscal_period=statement.fiscal_period,
        statement_date=statement.statement_date,
        version_sequence=statement.version_sequence,
        metric_code="REVENUE",
        metric_label="Revenue",
        unit="USD",
        period_start=None,
        period_end=statement.statement_date,
        value=123,
        dimension_key="default",
        dimensions={},
        source_line_item="Net sales",
    )

    identity = _FakeStatementIdentity(
        cik=cik,
        statement_type=statement.statement_type,
        fiscal_year=statement.fiscal_year,
        fiscal_period=statement.fiscal_period,
        version_sequence=statement.version_sequence,
    )

    fq = _FakeFactQuality(
        dq_run_id="dq-1",
        statement_identity=identity,
        metric_code="REVENUE",
        dimension_key="default",
        severity=MaterialityClass.LOW,
        is_present=True,
        is_non_negative=True,
        is_consistent_with_history=True,
        has_known_issue=False,
        details={"note": "ok"},
    )

    anomaly = _FakeAnomaly(
        dq_run_id="dq-1",
        metric_code="REVENUE",
        dimension_key="default",
        rule_code="NON_NEGATIVE",
        severity=MaterialityClass.LOW,
        message="Metric is slightly negative in some periods.",
        details={"threshold": "0"},
    )

    dq_run = _FakeDQRun(
        dq_run_id="dq-1",
        rule_set_version="v1",
        executed_at=datetime(2024, 4, 1, 12, 0, tzinfo=UTC),
    )

    statements_repo = _FakeStatementsRepository([statement])
    facts_repo = _FakeFactsRepository([fact])
    dq_repo = _FakeDQRepository(dq_run=dq_run, fact_quality=[fq], anomalies=[anomaly])

    uow = _FakeUnitOfWork(statements_repo, facts_repo, dq_repo)
    use_case = GetStatementWithDQOverlayUseCase(uow=uow)

    req = GetStatementWithDQOverlayRequest(
        cik=cik,
        statement_type=statement.statement_type,
        fiscal_year=statement.fiscal_year,
        fiscal_period=statement.fiscal_period,
        version_sequence=statement.version_sequence,
    )

    result = await use_case.execute(req)

    assert isinstance(result, StatementDQOverlayDTO)
    assert result.cik == cik
    assert result.statement_type == statement.statement_type
    assert result.fiscal_year == statement.fiscal_year
    assert result.fiscal_period == statement.fiscal_period
    assert result.version_sequence == statement.version_sequence

    assert result.accounting_standard == statement.accounting_standard
    assert result.statement_date == statement.statement_date
    assert result.currency == statement.currency

    # DQ run metadata
    assert result.dq_run_id == "dq-1"
    assert result.dq_rule_set_version == "v1"
    assert result.dq_executed_at == dq_run.executed_at

    # Facts + DQ alignment
    assert len(result.facts) == 1
    assert result.facts[0].metric_code == "REVENUE"
    assert len(result.fact_quality) == 1
    assert len(result.anomalies) == 1

    # max_severity aggregates across FQ + anomalies
    assert result.max_severity == MaterialityClass.LOW


@pytest.mark.asyncio
async def test_get_statement_with_dq_overlay_raises_if_statement_missing() -> None:
    statements_repo = _FakeStatementsRepository([])
    facts_repo = _FakeFactsRepository([])
    dq_repo = _FakeDQRepository(dq_run=None, fact_quality=[], anomalies=[])
    uow = _FakeUnitOfWork(statements_repo, facts_repo, dq_repo)

    use_case = GetStatementWithDQOverlayUseCase(uow=uow)

    req = GetStatementWithDQOverlayRequest(
        cik="0000999999",
        statement_type=StatementType.INCOME_STATEMENT,
        fiscal_year=2024,
        fiscal_period=FiscalPeriod.Q1,
        version_sequence=1,
    )

    with pytest.raises(EdgarIngestionError):
        await use_case.execute(req)
