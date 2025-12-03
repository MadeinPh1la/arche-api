# tests/unit/application/use_cases/statements/test_run_statement_dq.py
# Copyright (c) Stacklion.
# SPDX-License-Identifier: MIT
"""Unit tests for RunStatementDQUseCase."""

from __future__ import annotations

from datetime import date as _date
from decimal import Decimal
from typing import Any

import pytest

from stacklion_api.application.schemas.dto.edgar_dq import RunStatementDQResultDTO
from stacklion_api.application.uow import UnitOfWork as UnitOfWorkProtocol
from stacklion_api.application.use_cases.statements.run_statement_dq import (
    RunStatementDQRequest,
    RunStatementDQUseCase,
    _max_severity,
    _severity_rank,
)
from stacklion_api.domain.entities.edgar_dq import (
    EdgarDQAnomaly,
    EdgarDQRun,
    EdgarFactQuality,
    NormalizedStatementIdentity,
)
from stacklion_api.domain.entities.edgar_normalized_fact import EdgarNormalizedFact
from stacklion_api.domain.enums.edgar import FiscalPeriod, MaterialityClass, StatementType
from stacklion_api.domain.exceptions.edgar import EdgarIngestionError
from stacklion_api.domain.interfaces.repositories.edgar_dq_repository import EdgarDQRepository
from stacklion_api.domain.interfaces.repositories.edgar_facts_repository import EdgarFactsRepository


class _FakeFactsRepo(EdgarFactsRepository):
    """In-memory fake facts repository for DQ use-case tests."""

    def __init__(
        self,
        facts: list[EdgarNormalizedFact],
        history: list[EdgarNormalizedFact] | None = None,
    ) -> None:
        self._facts = list(facts)
        self._history = list(history or [])

    async def list_facts_for_statement(
        self,
        identity: NormalizedStatementIdentity,
    ) -> list[EdgarNormalizedFact]:
        return list(self._facts)

    async def list_facts_history(
        self,
        *,
        cik: str,
        statement_type: str,
        metric_code: str,
        limit: int,
    ) -> list[EdgarNormalizedFact]:
        # Ignore filters for tests; just return configured history slice.
        return self._history[:limit]

    # Other interface methods are not needed for these tests.


class _FakeDQRepo(EdgarDQRepository):
    """In-memory fake DQ repository capturing persisted artifacts."""

    def __init__(self) -> None:
        self.runs: list[EdgarDQRun] = []
        self.fact_quality: list[list[EdgarFactQuality]] = []
        self.anomalies: list[list[EdgarDQAnomaly]] = []

    async def create_run(
        self,
        run: EdgarDQRun,
        fact_quality: list[EdgarFactQuality],
        anomalies: list[EdgarDQAnomaly],
    ) -> None:
        self.runs.append(run)
        self.fact_quality.append(list(fact_quality))
        self.anomalies.append(list(anomalies))

    async def latest_run_for_statement(
        self,
        identity: NormalizedStatementIdentity,
    ) -> EdgarDQRun | None:
        return self.runs[-1] if self.runs else None

    async def list_anomalies_for_run(
        self,
        dq_run_id: str,
        min_severity: MaterialityClass | None = None,
        limit: int = 200,
    ) -> list[EdgarDQAnomaly]:
        return [a for run_anoms in self.anomalies for a in run_anoms]

    async def list_anomalies_for_statement(
        self,
        identity: NormalizedStatementIdentity,
        min_severity: MaterialityClass | None = None,
        limit: int = 200,
    ) -> list[EdgarDQAnomaly]:
        return [a for run_anoms in self.anomalies for a in run_anoms]

    async def list_fact_quality_for_statement(
        self,
        identity: NormalizedStatementIdentity,
    ) -> list[EdgarFactQuality]:
        return [fq for run_fq in self.fact_quality for fq in run_fq]


class _FakeTx(UnitOfWorkProtocol):
    """Simple in-memory transactional boundary for the use case."""

    def __init__(self, facts_repo: _FakeFactsRepo, dq_repo: _FakeDQRepo) -> None:
        self._facts_repo = facts_repo
        self._dq_repo = dq_repo
        self.committed = False

    async def __aenter__(self) -> _FakeTx:
        return self

    async def __aexit__(self, exc_type, exc, tb) -> None:  # type: ignore[override]
        # No-op for tests.
        return None

    def get_repository(self, repo_type: type[Any]) -> Any:  # type: ignore[override]
        # Identity comparison is enough; avoids runtime protocol checks.
        if repo_type is EdgarFactsRepository:
            return self._facts_repo
        if repo_type is EdgarDQRepository:
            return self._dq_repo
        raise KeyError(repo_type)

    async def commit(self) -> None:
        self.committed = True


_STATEMENT_DATE = _date(2024, 3, 31)


def _make_fact(value: Decimal) -> EdgarNormalizedFact:
    """Construct a minimal normalized fact for tests."""
    return EdgarNormalizedFact(
        cik="0000123456",
        statement_type=StatementType.INCOME_STATEMENT,
        accounting_standard="US_GAAP",
        fiscal_year=2024,
        fiscal_period=FiscalPeriod.Q1,
        statement_date=_STATEMENT_DATE,
        version_sequence=1,
        metric_code="REVENUE",
        metric_label=None,
        unit="USD",
        period_start=None,
        period_end=_STATEMENT_DATE,
        value=value,
        dimensions={},
        dimension_key="default",
        source_line_item=None,
    )


# --------------------------------------------------------------------------- #
# execute() invariants                                                       #
# --------------------------------------------------------------------------- #


@pytest.mark.asyncio
async def test_execute_raises_for_empty_cik() -> None:
    facts_repo = _FakeFactsRepo(facts=[])
    dq_repo = _FakeDQRepo()
    uow = _FakeTx(facts_repo, dq_repo)

    use_case = RunStatementDQUseCase(uow=uow)

    req = RunStatementDQRequest(
        cik="  ",
        statement_type=StatementType.INCOME_STATEMENT,
        fiscal_year=2024,
        fiscal_period=FiscalPeriod.Q1,
        version_sequence=1,
    )

    with pytest.raises(EdgarIngestionError):
        await use_case.execute(req)


@pytest.mark.asyncio
async def test_execute_raises_when_no_facts_exist() -> None:
    """When no facts exist for the identity, raise EdgarIngestionError."""
    facts_repo = _FakeFactsRepo(facts=[])
    dq_repo = _FakeDQRepo()
    uow = _FakeTx(facts_repo, dq_repo)

    use_case = RunStatementDQUseCase(uow=uow)

    req = RunStatementDQRequest(
        cik="0000123456",
        statement_type=StatementType.INCOME_STATEMENT,
        fiscal_year=2024,
        fiscal_period=FiscalPeriod.Q1,
        version_sequence=1,
    )

    with pytest.raises(EdgarIngestionError):
        await use_case.execute(req)

    assert not dq_repo.runs
    assert not uow.committed


@pytest.mark.asyncio
async def test_execute_success_persists_run_and_artifacts_and_returns_dto() -> None:
    """Happy path: facts exist, rules produce artifacts, and run is persisted."""
    current_fact = _make_fact(Decimal("-200"))
    history_fact = _make_fact(Decimal("10"))

    facts_repo = _FakeFactsRepo(facts=[current_fact], history=[history_fact])
    dq_repo = _FakeDQRepo()
    uow = _FakeTx(facts_repo, dq_repo)

    use_case = RunStatementDQUseCase(uow=uow)

    req = RunStatementDQRequest(
        cik="0000123456",
        statement_type=StatementType.INCOME_STATEMENT,
        fiscal_year=2024,
        fiscal_period=FiscalPeriod.Q1,
        version_sequence=1,
        history_lookback=3,
    )

    result = await use_case.execute(req)

    assert isinstance(result, RunStatementDQResultDTO)
    assert result.cik == "0000123456"
    assert result.statement_type == StatementType.INCOME_STATEMENT
    assert result.total_fact_quality == 1
    assert result.total_anomalies >= 1
    assert result.dq_run_id
    assert result.max_severity in (MaterialityClass.LOW, MaterialityClass.MEDIUM)
    assert dq_repo.runs
    assert dq_repo.fact_quality
    assert uow.committed is True


# --------------------------------------------------------------------------- #
# History-consistency rule coverage                                          #
# --------------------------------------------------------------------------- #


@pytest.mark.asyncio
async def test_execute_marks_history_consistent_without_spike() -> None:
    """History present with moderate change should set consistency=True and no spike anomaly."""
    current_fact = _make_fact(Decimal("110"))
    history_fact = _make_fact(Decimal("100"))  # +10% change

    facts_repo = _FakeFactsRepo(facts=[current_fact], history=[history_fact])
    dq_repo = _FakeDQRepo()
    uow = _FakeTx(facts_repo, dq_repo)

    use_case = RunStatementDQUseCase(uow=uow)

    req = RunStatementDQRequest(
        cik="0000123456",
        statement_type=StatementType.INCOME_STATEMENT,
        fiscal_year=2024,
        fiscal_period=FiscalPeriod.Q1,
        version_sequence=1,
        history_lookback=4,
    )

    result = await use_case.execute(req)

    # No HISTORY_SPIKE anomalies expected.
    spike_codes = {a.rule_code for run in dq_repo.anomalies for a in run}
    assert "HISTORY_SPIKE" not in spike_codes

    # Fact quality should record consistency=True.
    fq_items = dq_repo.fact_quality[0]
    assert len(fq_items) == 1
    assert fq_items[0].is_consistent_with_history is True
    # Severity should be NONE because no rules fired.
    assert result.max_severity in (MaterialityClass.NONE, None)


@pytest.mark.asyncio
async def test_execute_history_zero_sets_consistency_unknown() -> None:
    """When last history value is zero, history-consistency is set to None and no spike is emitted."""
    current_fact = _make_fact(Decimal("100"))
    history_fact_zero = _make_fact(Decimal("0"))

    facts_repo = _FakeFactsRepo(facts=[current_fact], history=[history_fact_zero])
    dq_repo = _FakeDQRepo()
    uow = _FakeTx(facts_repo, dq_repo)

    use_case = RunStatementDQUseCase(uow=uow)

    req = RunStatementDQRequest(
        cik="0000123456",
        statement_type=StatementType.INCOME_STATEMENT,
        fiscal_year=2024,
        fiscal_period=FiscalPeriod.Q1,
        version_sequence=1,
        history_lookback=4,
    )

    await use_case.execute(req)

    # No HISTORY_SPIKE anomalies when previous value is zero.
    spike_codes = {a.rule_code for run in dq_repo.anomalies for a in run}
    assert "HISTORY_SPIKE" not in spike_codes

    fq_items = dq_repo.fact_quality[0]
    assert fq_items[0].is_consistent_with_history is None


# --------------------------------------------------------------------------- #
# _severity_rank / _max_severity                                             #
# --------------------------------------------------------------------------- #


def test_severity_rank_orders_by_materiality() -> None:
    """_severity_rank should reflect NONE < LOW < MEDIUM < HIGH."""
    order = [
        MaterialityClass.NONE,
        MaterialityClass.LOW,
        MaterialityClass.MEDIUM,
        MaterialityClass.HIGH,
    ]
    ranks = [_severity_rank(s) for s in order]

    assert ranks == sorted(ranks)
    assert _severity_rank(MaterialityClass.HIGH) > _severity_rank(MaterialityClass.LOW)


def test_max_severity_handles_empty_and_mixed_sequences() -> None:
    """_max_severity should return None for empty inputs and highest severity otherwise."""
    # Empty case.
    assert _max_severity([], []) is None

    identity = NormalizedStatementIdentity(
        cik="0000123456",
        statement_type=StatementType.INCOME_STATEMENT,
        fiscal_year=2024,
        fiscal_period=FiscalPeriod.Q1,
        version_sequence=1,
    )

    fq_low = EdgarFactQuality(
        dq_run_id="run",
        statement_identity=identity,
        metric_code="M1",
        dimension_key="default",
        severity=MaterialityClass.LOW,
        is_present=True,
        is_non_negative=True,
        is_consistent_with_history=True,
        has_known_issue=False,
        details=None,
    )
    anom_high = EdgarDQAnomaly(
        dq_run_id="run",
        statement_identity=identity,
        metric_code="M2",
        dimension_key="default",
        rule_code="RULE",
        severity=MaterialityClass.HIGH,
        message="msg",
        details={},
    )

    result = _max_severity([fq_low], [anom_high])
    assert result is MaterialityClass.HIGH
