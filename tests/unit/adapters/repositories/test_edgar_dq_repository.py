# tests/unit/adapters/repositories/test_edgar_dq_repository.py
# Copyright (c)
# SPDX-License-Identifier: MIT
"""Tests for EdgarDQRepository.

Design:
    These tests use a fully in-memory FakeSession instead of a real DB.
    The goal is high line + branch coverage of edgar_dq_repository without
    relying on any external pytest fixtures.
"""

from __future__ import annotations

from collections.abc import Iterable, Sequence
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any, cast
from uuid import UUID, uuid4

import pytest

from stacklion_api.adapters.repositories.edgar_dq_repository import (
    EdgarDQRepository,
    _materiality_rank,
)
from stacklion_api.domain.entities.edgar_dq import (
    EdgarDQAnomaly,
    EdgarDQRun,
    EdgarFactQuality,
    NormalizedStatementIdentity,
)
from stacklion_api.domain.enums.edgar import FiscalPeriod, MaterialityClass, StatementType
from stacklion_api.domain.exceptions.edgar import EdgarIngestionError

# --------------------------------------------------------------------------- #
# Domain helpers                                                              #
# --------------------------------------------------------------------------- #


def _make_identity(
    *,
    cik: str = "0000123456",
    statement_type: StatementType = StatementType.INCOME_STATEMENT,
    fiscal_year: int = 2024,
    fiscal_period: FiscalPeriod = FiscalPeriod.Q1,
    version_sequence: int = 1,
) -> NormalizedStatementIdentity:
    return NormalizedStatementIdentity(
        cik=cik,
        statement_type=statement_type,
        fiscal_year=fiscal_year,
        fiscal_period=fiscal_period,
        version_sequence=version_sequence,
    )


def _make_run(
    *,
    dq_run_id: str | None = None,
    statement_identity: NormalizedStatementIdentity | None = None,
    executed_at: datetime | None = None,
) -> EdgarDQRun:
    return EdgarDQRun(
        dq_run_id=dq_run_id or str(uuid4()),
        statement_identity=statement_identity,
        rule_set_version="v1",
        scope_type="STATEMENT",
        executed_at=executed_at or datetime.now(tz=UTC),
    )


def _make_fact_quality(
    *,
    dq_run_id: str,
    identity: NormalizedStatementIdentity | None,
    metric_code: str = "REVENUE",
    dimension_key: str = "default",
    severity: MaterialityClass = MaterialityClass.NONE,
    is_present: bool = True,
    is_non_negative: bool = True,
    is_consistent_with_history: bool | None = True,
    has_known_issue: bool = False,
) -> EdgarFactQuality:
    return EdgarFactQuality(
        dq_run_id=dq_run_id,
        statement_identity=identity,
        metric_code=metric_code,
        dimension_key=dimension_key,
        severity=severity,
        is_present=is_present,
        is_non_negative=is_non_negative,
        is_consistent_with_history=is_consistent_with_history,
        has_known_issue=has_known_issue,
        details={"note": "test"},
    )


def _make_anomaly(
    *,
    dq_run_id: str,
    metric_code: str = "REVENUE",
    dimension_key: str = "default",
    rule_code: str = "TEST_RULE",
    severity: MaterialityClass = MaterialityClass.LOW,
) -> EdgarDQAnomaly:
    return EdgarDQAnomaly(
        dq_run_id=dq_run_id,
        statement_identity=None,
        metric_code=metric_code,
        dimension_key=dimension_key,
        rule_code=rule_code,
        severity=severity,
        message="test anomaly",
        details={"k": "v"},
    )


# --------------------------------------------------------------------------- #
# Fake DB rows (duck-typed against ORM models)                                #
# --------------------------------------------------------------------------- #


@dataclass
class _FakeCompanyRow:
    cik: str | None
    company_id: str


@dataclass
class _FakeStatementVersionRow:
    statement_version_id: UUID
    statement_type: str
    fiscal_year: int
    fiscal_period: str
    version_sequence: int


@dataclass
class _FakeRunRow:
    dq_run_id: UUID
    cik: str | None
    statement_type: str | None
    fiscal_year: int | None
    fiscal_period: str | None
    version_sequence: int | None
    rule_set_version: str
    scope_type: str
    executed_at: datetime


@dataclass
class _FakeFactQualityRow:
    dq_run_id: UUID
    cik: str
    statement_type: str
    fiscal_year: int
    fiscal_period: str
    version_sequence: int
    metric_code: str
    dimension_key: str
    severity: str
    is_present: bool
    is_non_negative: bool
    is_consistent_with_history: bool | None
    has_known_issue: bool
    details: dict[str, Any] | None


@dataclass
class _FakeAnomalyRow:
    dq_run_id: UUID
    metric_code: str
    dimension_key: str
    rule_code: str
    severity: str
    message: str
    details: dict[str, Any] | None


# --------------------------------------------------------------------------- #
# Fake SQLAlchemy Result + Session                                            #
# --------------------------------------------------------------------------- #


class _FakeScalars:
    def __init__(self, rows: Sequence[Any]) -> None:
        self._rows = list(rows)

    def all(self) -> list[Any]:
        return list(self._rows)


class _FakeResult:
    """Mimic the subset of SQLAlchemy Result used by the repo."""

    def __init__(self, rows: Sequence[Any]) -> None:
        self._rows = list(rows)

    def scalar_one_or_none(self) -> Any:
        return self._rows[0] if self._rows else None

    def scalars(self) -> _FakeScalars:
        return _FakeScalars(self._rows)


class _FakeSession:
    """Minimal AsyncSession replacement with pre-baked results."""

    def __init__(self, results: Iterable[Sequence[Any]] | None = None) -> None:
        # Each call to execute() pops the next list of rows.
        self._results: list[Sequence[Any]] = list(results or [])
        self.calls: list[Any] = []

    async def execute(self, stmt: Any) -> _FakeResult:  # noqa: D401
        """Record the statement and return the next pre-configured result."""
        self.calls.append(stmt)
        rows = self._results.pop(0) if self._results else []
        return _FakeResult(rows)


# --------------------------------------------------------------------------- #
# Tests for create_run                                                        #
# --------------------------------------------------------------------------- #


@pytest.mark.asyncio
async def test_create_run_persists_without_resolving_identity() -> None:
    """create_run should execute inserts when statement_identity is None."""
    fake_session = _FakeSession()
    repo = EdgarDQRepository(session=cast(Any, fake_session))

    dq_run = _make_run(statement_identity=None)
    identity = _make_identity()
    fq_rows = [
        _make_fact_quality(
            dq_run_id=dq_run.dq_run_id,
            identity=identity,
            metric_code="REVENUE",
            severity=MaterialityClass.NONE,
        ),
        _make_fact_quality(
            dq_run_id=dq_run.dq_run_id,
            identity=identity,
            metric_code="NET_INCOME",
            severity=MaterialityClass.LOW,
        ),
    ]
    anomalies = [
        _make_anomaly(dq_run_id=dq_run.dq_run_id, severity=MaterialityClass.LOW),
        _make_anomaly(dq_run_id=dq_run.dq_run_id, severity=MaterialityClass.MEDIUM),
    ]

    await repo.create_run(run=dq_run, fact_quality=fq_rows, anomalies=anomalies)

    # 1 insert for run, 1 for fact-quality batch, 1 for anomalies batch
    assert len(fake_session.calls) == 3


@pytest.mark.asyncio
async def test_create_run_raises_if_fact_quality_missing_identity() -> None:
    """_fact_quality_to_row should enforce presence of statement_identity."""
    fake_session = _FakeSession()
    repo = EdgarDQRepository(session=cast(Any, fake_session))

    dq_run = _make_run(statement_identity=None)
    fq = _make_fact_quality(
        dq_run_id=dq_run.dq_run_id,
        identity=None,  # invalid → should throw
    )

    with pytest.raises(EdgarIngestionError):
        await repo.create_run(run=dq_run, fact_quality=[fq], anomalies=[])


# --------------------------------------------------------------------------- #
# Tests for _resolve_statement_identity + latest_run_for_statement            #
# --------------------------------------------------------------------------- #


@pytest.mark.asyncio
async def test_resolve_statement_identity_success() -> None:
    """_resolve_statement_identity should map company + statement_version rows."""
    identity = _make_identity()

    company = _FakeCompanyRow(cik=identity.cik, company_id="company-1")
    sv = _FakeStatementVersionRow(
        statement_version_id=uuid4(),
        statement_type=identity.statement_type.value,
        fiscal_year=identity.fiscal_year,
        fiscal_period=identity.fiscal_period.value,
        version_sequence=identity.version_sequence,
    )

    fake_session = _FakeSession(results=[[company], [sv]])
    repo = EdgarDQRepository(session=cast(Any, fake_session))

    (
        statement_version_id,
        cik,
        stmt_type,
        fy,
        fp,
        vs,
    ) = await repo._resolve_statement_identity(identity)

    assert cik == identity.cik
    assert stmt_type == identity.statement_type.value
    assert fy == identity.fiscal_year
    assert fp == identity.fiscal_period.value
    assert vs == identity.version_sequence
    assert isinstance(statement_version_id, UUID)


@pytest.mark.asyncio
async def test_resolve_statement_identity_missing_company_raises() -> None:
    """Missing company row should raise EdgarIngestionError."""
    identity = _make_identity()
    fake_session = _FakeSession(results=[[]])  # no company row
    repo = EdgarDQRepository(session=cast(Any, fake_session))

    with pytest.raises(EdgarIngestionError):
        await repo._resolve_statement_identity(identity)


@pytest.mark.asyncio
async def test_resolve_statement_identity_missing_statement_version_raises() -> None:
    """Missing statement_version row should raise EdgarIngestionError."""
    identity = _make_identity()
    company = _FakeCompanyRow(cik=identity.cik, company_id="company-1")

    fake_session = _FakeSession(results=[[company], []])
    repo = EdgarDQRepository(session=cast(Any, fake_session))

    with pytest.raises(EdgarIngestionError):
        await repo._resolve_statement_identity(identity)


@pytest.mark.asyncio
async def test_latest_run_for_statement_returns_none_when_no_run() -> None:
    """latest_run_for_statement should return None if no DQ run exists."""
    identity = _make_identity()
    company = _FakeCompanyRow(cik=identity.cik, company_id="company-1")
    sv = _FakeStatementVersionRow(
        statement_version_id=uuid4(),
        statement_type=identity.statement_type.value,
        fiscal_year=identity.fiscal_year,
        fiscal_period=identity.fiscal_period.value,
        version_sequence=identity.version_sequence,
    )

    fake_session = _FakeSession(results=[[company], [sv], []])  # no run row
    repo = EdgarDQRepository(session=cast(Any, fake_session))

    result = await repo.latest_run_for_statement(identity)
    assert result is None


@pytest.mark.asyncio
async def test_latest_run_for_statement_maps_run_to_domain() -> None:
    """latest_run_for_statement should map run row → EdgarDQRun with identity."""
    identity = _make_identity()
    company = _FakeCompanyRow(cik=identity.cik, company_id="company-1")
    sv = _FakeStatementVersionRow(
        statement_version_id=uuid4(),
        statement_type=identity.statement_type.value,
        fiscal_year=identity.fiscal_year,
        fiscal_period=identity.fiscal_period.value,
        version_sequence=identity.version_sequence,
    )
    run_row = _FakeRunRow(
        dq_run_id=uuid4(),
        cik=identity.cik,
        statement_type=identity.statement_type.value,
        fiscal_year=identity.fiscal_year,
        fiscal_period=identity.fiscal_period.value,
        version_sequence=identity.version_sequence,
        rule_set_version="v1",
        scope_type="STATEMENT",
        executed_at=datetime(2024, 1, 1, tzinfo=UTC),
    )

    fake_session = _FakeSession(results=[[company], [sv], [run_row]])
    repo = EdgarDQRepository(session=cast(Any, fake_session))

    result = await repo.latest_run_for_statement(identity)
    assert isinstance(result, EdgarDQRun)
    assert result.dq_run_id == str(run_row.dq_run_id)
    assert result.statement_identity is not None
    assert result.statement_identity.cik == identity.cik
    assert result.statement_identity.statement_type == identity.statement_type
    assert result.rule_set_version == "v1"


# --------------------------------------------------------------------------- #
# Tests for list_fact_quality_for_statement                                   #
# --------------------------------------------------------------------------- #


@pytest.mark.asyncio
async def test_list_fact_quality_for_statement_roundtrip() -> None:
    """list_fact_quality_for_statement should map rows to domain entities."""
    identity = _make_identity()
    dq_run_id = uuid4()

    company = _FakeCompanyRow(cik=identity.cik, company_id="company-1")
    sv = _FakeStatementVersionRow(
        statement_version_id=uuid4(),
        statement_type=identity.statement_type.value,
        fiscal_year=identity.fiscal_year,
        fiscal_period=identity.fiscal_period.value,
        version_sequence=identity.version_sequence,
    )

    fq_rows = [
        _FakeFactQualityRow(
            dq_run_id=dq_run_id,
            cik=identity.cik,
            statement_type=identity.statement_type.value,
            fiscal_year=identity.fiscal_year,
            fiscal_period=identity.fiscal_period.value,
            version_sequence=identity.version_sequence,
            metric_code="REVENUE",
            dimension_key="default",
            severity=MaterialityClass.NONE.value,
            is_present=True,
            is_non_negative=True,
            is_consistent_with_history=True,
            has_known_issue=False,
            details={"a": 1},
        ),
        _FakeFactQualityRow(
            dq_run_id=dq_run_id,
            cik=identity.cik,
            statement_type=identity.statement_type.value,
            fiscal_year=identity.fiscal_year,
            fiscal_period=identity.fiscal_period.value,
            version_sequence=identity.version_sequence,
            metric_code="NET_INCOME",
            dimension_key="default",
            severity=MaterialityClass.MEDIUM.value,
            is_present=True,
            is_non_negative=True,
            is_consistent_with_history=None,
            has_known_issue=True,
            details={"b": 2},
        ),
    ]

    fake_session = _FakeSession(results=[[company], [sv], fq_rows])
    repo = EdgarDQRepository(session=cast(Any, fake_session))

    result = await repo.list_fact_quality_for_statement(identity)
    assert len(result) == 2

    codes = {fq.metric_code for fq in result}
    assert codes == {"REVENUE", "NET_INCOME"}

    severities = {fq.metric_code: fq.severity for fq in result}
    assert severities["REVENUE"] == MaterialityClass.NONE
    assert severities["NET_INCOME"] == MaterialityClass.MEDIUM


# --------------------------------------------------------------------------- #
# Tests for list_anomalies_for_run / list_anomalies_for_statement             #
# --------------------------------------------------------------------------- #


@pytest.mark.asyncio
async def test_list_anomalies_for_run_min_severity_and_limit() -> None:
    """list_anomalies_for_run must honor min_severity and limit."""
    dq_run_id = str(uuid4())
    rows = [
        _FakeAnomalyRow(
            dq_run_id=UUID(dq_run_id),
            metric_code="REVENUE",
            dimension_key="d",
            rule_code="R0",
            severity=MaterialityClass.NONE.value,
            message="none",
            details=None,
        ),
        _FakeAnomalyRow(
            dq_run_id=UUID(dq_run_id),
            metric_code="REVENUE",
            dimension_key="d",
            rule_code="R1",
            severity=MaterialityClass.LOW.value,
            message="low",
            details=None,
        ),
        _FakeAnomalyRow(
            dq_run_id=UUID(dq_run_id),
            metric_code="REVENUE",
            dimension_key="d",
            rule_code="R2",
            severity=MaterialityClass.MEDIUM.value,
            message="med",
            details=None,
        ),
        _FakeAnomalyRow(
            dq_run_id=UUID(dq_run_id),
            metric_code="REVENUE",
            dimension_key="d",
            rule_code="R3",
            severity=MaterialityClass.HIGH.value,
            message="high",
            details=None,
        ),
    ]

    fake_session = _FakeSession(results=[rows])
    repo = EdgarDQRepository(session=cast(Any, fake_session))

    # Filter by MEDIUM+
    filtered = await repo.list_anomalies_for_run(
        dq_run_id=dq_run_id,
        min_severity=MaterialityClass.MEDIUM,
        limit=10,
    )
    severities = {a.severity for a in filtered}
    assert severities == {MaterialityClass.MEDIUM, MaterialityClass.HIGH}

    # Limit to first 2 after ordering
    fake_session2 = _FakeSession(results=[rows])
    repo2 = EdgarDQRepository(session=cast(Any, fake_session2))

    limited = await repo2.list_anomalies_for_run(
        dq_run_id=dq_run_id,
        min_severity=None,
        limit=2,
    )
    assert len(limited) == 2


@pytest.mark.asyncio
async def test_list_anomalies_for_statement_uses_latest_run() -> None:
    """list_anomalies_for_statement should call latest_run_for_statement and filter."""
    identity = _make_identity()

    company = _FakeCompanyRow(cik=identity.cik, company_id="company-1")
    sv = _FakeStatementVersionRow(
        statement_version_id=uuid4(),
        statement_type=identity.statement_type.value,
        fiscal_year=identity.fiscal_year,
        fiscal_period=identity.fiscal_period.value,
        version_sequence=identity.version_sequence,
    )
    run_row = _FakeRunRow(
        dq_run_id=uuid4(),
        cik=identity.cik,
        statement_type=identity.statement_type.value,
        fiscal_year=identity.fiscal_year,
        fiscal_period=identity.fiscal_period.value,
        version_sequence=identity.version_sequence,
        rule_set_version="v1",
        scope_type="STATEMENT",
        executed_at=datetime(2024, 2, 1, tzinfo=UTC),
    )
    anom_rows = [
        _FakeAnomalyRow(
            dq_run_id=run_row.dq_run_id,
            metric_code="REVENUE",
            dimension_key="d",
            rule_code="NEW",
            severity=MaterialityClass.MEDIUM.value,
            message="new",
            details=None,
        ),
    ]

    # Call order:
    # 1) _get_company_by_cik → [company]
    # 2) select StatementVersion → [sv]
    # 3) select dq_run → [run_row]
    # 4) select anomalies → [anom_rows]
    fake_session = _FakeSession(results=[[company], [sv], [run_row], anom_rows])
    repo = EdgarDQRepository(session=cast(Any, fake_session))

    result = await repo.list_anomalies_for_statement(identity, min_severity=None, limit=10)
    assert len(result) == 1
    assert result[0].rule_code == "NEW"


@pytest.mark.asyncio
async def test_list_anomalies_for_statement_returns_empty_when_no_run() -> None:
    """If latest_run_for_statement returns None, anomalies list should be empty."""
    identity = _make_identity()

    company = _FakeCompanyRow(cik=identity.cik, company_id="company-1")
    sv = _FakeStatementVersionRow(
        statement_version_id=uuid4(),
        statement_type=identity.statement_type.value,
        fiscal_year=identity.fiscal_year,
        fiscal_period=identity.fiscal_period.value,
        version_sequence=identity.version_sequence,
    )

    # No run row for the run-select call.
    fake_session = _FakeSession(results=[[company], [sv], []])
    repo = EdgarDQRepository(session=cast(Any, fake_session))

    result = await repo.list_anomalies_for_statement(identity, min_severity=None, limit=10)
    assert result == []


# --------------------------------------------------------------------------- #
# Tests for _materiality_rank                                                 #
# --------------------------------------------------------------------------- #


def test_materiality_rank_orders_severities() -> None:
    """_materiality_rank should impose deterministic ordering across severities."""
    assert _materiality_rank(MaterialityClass.NONE) < _materiality_rank(MaterialityClass.LOW)
    assert _materiality_rank(MaterialityClass.LOW) < _materiality_rank(MaterialityClass.MEDIUM)
    assert _materiality_rank(MaterialityClass.MEDIUM) < _materiality_rank(MaterialityClass.HIGH)
