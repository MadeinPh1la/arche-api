# tests/unit/application/use_cases/statements/test_get_statement_override_trace.py
# Copyright (c)
# SPDX-License-Identifier: MIT
"""Tests for GetStatementOverrideTraceUseCase."""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from datetime import date
from typing import Any

import pytest

from stacklion_api.application.use_cases.statements.get_statement_override_trace import (
    GetStatementOverrideTraceRequest,
    GetStatementOverrideTraceUseCase,
)
from stacklion_api.domain.entities.xbrl_override_observability import (
    EffectiveOverrideDecisionSummary,
    OverrideTraceEntry,
    StatementOverrideObservability,
)
from stacklion_api.domain.enums.canonical_statement_metric import CanonicalStatementMetric
from stacklion_api.domain.enums.edgar import AccountingStandard, FiscalPeriod, StatementType
from stacklion_api.domain.exceptions.edgar import EdgarIngestionError, EdgarMappingError
from stacklion_api.domain.services.xbrl_mapping_overrides import (
    MappingOverrideRule,
    OverrideScope,
)

# ---------------------------------------------------------------------------
# Fakes
# ---------------------------------------------------------------------------


@dataclass
class FakeNormalizedPayload:
    """Minimal normalized payload shape for tests."""

    source_taxonomy: str


@dataclass
class FakeStatementVersion:
    """Minimal EDGAR statement version shape for tests."""

    cik: str
    statement_type: StatementType
    accounting_standard: AccountingStandard
    statement_date: date
    fiscal_year: int
    fiscal_period: FiscalPeriod
    currency: str
    accession_id: str
    version_sequence: int
    normalized_payload: FakeNormalizedPayload | None
    industry_code: str | None = None


@dataclass
class FakeMappingOverrideRule:
    """Minimal override rule for filtering tests."""

    base_metric: CanonicalStatementMetric


class FakeStatementsRepository:
    """Fake EDGAR statements repository."""

    def __init__(self, versions: Sequence[FakeStatementVersion]) -> None:
        self._versions = list(versions)
        self.calls: list[dict[str, Any]] = []

    async def list_statement_versions_for_company(
        self,
        *,
        cik: str,
        statement_type: StatementType,
        fiscal_year: int,
        fiscal_period: FiscalPeriod,
    ) -> Sequence[FakeStatementVersion]:
        self.calls.append(
            {
                "cik": cik,
                "statement_type": statement_type,
                "fiscal_year": fiscal_year,
                "fiscal_period": fiscal_period,
            }
        )
        return list(self._versions)


class FakeOverridesRepository:
    """Fake XBRL mapping overrides repository."""

    def __init__(self, rules: Sequence[MappingOverrideRule]) -> None:
        self._rules = list(rules)
        self.list_all_rules_calls = 0
        self.list_rules_for_concept_calls: list[dict[str, Any]] = []

    async def list_all_rules(self) -> Sequence[MappingOverrideRule]:
        self.list_all_rules_calls += 1
        return list(self._rules)

    async def list_rules_for_concept(
        self,
        *,
        concept: str,
        taxonomy: str | None = None,
    ) -> Sequence[MappingOverrideRule]:
        self.list_rules_for_concept_calls.append(
            {
                "concept": concept,
                "taxonomy": taxonomy,
            }
        )
        return list(self._rules)


class FakeTx:
    """Fake transaction object returned by the UnitOfWork."""

    def __init__(
        self,
        statements_repo: FakeStatementsRepository,
        overrides_repo: FakeOverridesRepository,
    ) -> None:
        # These attribute names are what the helpers in the use case inspect.
        self.repo = statements_repo
        self.overrides_repo = overrides_repo


class FakeUnitOfWork:
    """Fake UnitOfWork implementing the async context manager protocol."""

    def __init__(
        self,
        statements_repo: FakeStatementsRepository,
        overrides_repo: FakeOverridesRepository,
    ) -> None:
        self._tx = FakeTx(statements_repo=statements_repo, overrides_repo=overrides_repo)
        self.enter_calls = 0
        self.exit_calls = 0

    async def __aenter__(self) -> FakeTx:
        self.enter_calls += 1
        return self._tx

    async def __aexit__(self, exc_type, exc, tb) -> None:
        self.exit_calls += 1


class FakeObservabilityService:
    """Fake observability service returning a pre-canned result."""

    def __init__(self, result: StatementOverrideObservability) -> None:
        self.result = result
        self.calls: list[dict[str, Any]] = []

    def inspect_overrides(self, context: Any) -> StatementOverrideObservability:
        self.calls.append(
            {
                "cik": context.cik,
                "statement_type": context.statement_type,
                "fiscal_year": context.fiscal_year,
                "fiscal_period": context.fiscal_period,
                "taxonomy": context.taxonomy,
            }
        )
        return self.result


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def base_statement_version() -> FakeStatementVersion:
    """Provide a baseline fake statement version."""
    return FakeStatementVersion(
        cik="0000320193",
        statement_type=StatementType.INCOME_STATEMENT,
        accounting_standard=AccountingStandard.US_GAAP,
        statement_date=date(2024, 9, 28),
        fiscal_year=2024,
        fiscal_period=FiscalPeriod.FY,
        currency="USD",
        accession_id="0000320193-24-000010",
        version_sequence=2,
        normalized_payload=FakeNormalizedPayload(source_taxonomy="US_GAAP_2024"),
    )


@pytest.fixture
def base_observability() -> StatementOverrideObservability:
    """Provide a minimal StatementOverrideObservability instance."""
    metric = CanonicalStatementMetric.REVENUE
    decision = EffectiveOverrideDecisionSummary(
        base_metric=metric,
        final_metric=None,
        applied_rule_id=123,
        applied_scope=None,
        is_suppression=False,
    )
    trace_entry = OverrideTraceEntry(
        rule_id=123,
        scope=OverrideScope.GLOBAL,
        matched=True,
        is_suppression=False,
        base_metric=metric,
        final_metric=metric,
        match_dimensions={"segment": "CONSOLIDATED"},
        match_cik=True,
        match_industry_code=False,
        match_analyst_id=False,
        priority=10,
    )

    return StatementOverrideObservability(
        cik="0000320193",
        statement_type=StatementType.INCOME_STATEMENT,
        fiscal_year=2024,
        fiscal_period=FiscalPeriod.FY,
        version_sequence=2,
        suppression_count=0,
        remap_count=0,
        per_metric_decisions={metric: decision},
        per_metric_traces={metric: (trace_entry,)},
    )


# ---------------------------------------------------------------------------
# Tests: happy path
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_execute_happy_path_filters_and_maps_to_dto(
    base_statement_version: FakeStatementVersion,
    base_observability: StatementOverrideObservability,
) -> None:
    """Happy path: returns DTO with mapped decisions and traces."""
    statements_repo = FakeStatementsRepository(versions=[base_statement_version])
    rules = [FakeMappingOverrideRule(base_metric=CanonicalStatementMetric.REVENUE)]
    overrides_repo = FakeOverridesRepository(rules=rules)
    uow = FakeUnitOfWork(statements_repo=statements_repo, overrides_repo=overrides_repo)

    use_case = GetStatementOverrideTraceUseCase(uow=uow)
    # Inject fake observability service so we control the domain result.
    fake_service = FakeObservabilityService(result=base_observability)
    use_case._observability_service = fake_service  # type: ignore[attr-defined]

    req = GetStatementOverrideTraceRequest(
        cik=base_statement_version.cik,
        statement_type=base_statement_version.statement_type,
        fiscal_year=base_statement_version.fiscal_year,
        fiscal_period=base_statement_version.fiscal_period,
        version_sequence=base_statement_version.version_sequence,
        gaap_concept=None,
        canonical_metric_code="REVENUE",
        dimension_key="segment:CONSOLIDATED",
    )

    dto = await use_case.execute(req)

    # UnitOfWork boundaries are respected.
    assert uow.enter_calls == 1
    assert uow.exit_calls == 1

    # Overrides repository used via list_all_rules (no gaap_concept in this test).
    assert overrides_repo.list_all_rules_calls == 1
    assert overrides_repo.list_rules_for_concept_calls == []

    # Observability service invoked with the correct identity.
    assert len(fake_service.calls) == 1
    call = fake_service.calls[0]
    assert call["cik"] == base_statement_version.cik
    assert call["statement_type"] == base_statement_version.statement_type
    assert call["fiscal_year"] == base_statement_version.fiscal_year
    assert call["fiscal_period"] == base_statement_version.fiscal_period
    assert call["taxonomy"] == "US_GAAP_2024"

    # DTO headers mirror the observability entity.
    assert dto.cik == base_observability.cik
    assert dto.statement_type == base_observability.statement_type
    assert dto.fiscal_year == base_observability.fiscal_year
    assert dto.fiscal_period == base_observability.fiscal_period
    assert dto.version_sequence == base_observability.version_sequence
    assert dto.suppression_count == base_observability.suppression_count
    assert dto.remap_count == base_observability.remap_count
    assert dto.dimension_key == "segment:CONSOLIDATED"

    # Decisions are keyed by canonical metric code.
    assert "REVENUE" in dto.decisions
    decision = dto.decisions["REVENUE"]
    assert decision.base_metric == "REVENUE"
    # final_metric is None in the base_observability we set up.
    assert decision.final_metric is None
    assert decision.is_suppression is False

    # Traces are present and correctly mapped.
    assert "REVENUE" in dto.traces
    trace_entries = dto.traces["REVENUE"]
    assert len(trace_entries) == 1
    trace = trace_entries[0]
    assert trace.rule_id == "123"
    assert trace.scope == OverrideScope.GLOBAL.value
    assert trace.base_metric == "REVENUE"
    assert trace.final_metric == "REVENUE"
    assert trace.match_dimensions == {"segment": "CONSOLIDATED"}


@pytest.mark.asyncio
async def test_execute_uses_list_rules_for_concept_when_gaap_concept_provided(
    base_statement_version: FakeStatementVersion,
    base_observability: StatementOverrideObservability,
) -> None:
    """When gaap_concept is provided, use list_rules_for_concept()."""
    statements_repo = FakeStatementsRepository(versions=[base_statement_version])
    rules = [FakeMappingOverrideRule(base_metric=CanonicalStatementMetric.REVENUE)]
    overrides_repo = FakeOverridesRepository(rules=rules)
    uow = FakeUnitOfWork(statements_repo=statements_repo, overrides_repo=overrides_repo)

    use_case = GetStatementOverrideTraceUseCase(uow=uow)
    use_case._observability_service = FakeObservabilityService(  # type: ignore[attr-defined]
        result=base_observability,
    )

    req = GetStatementOverrideTraceRequest(
        cik=base_statement_version.cik,
        statement_type=base_statement_version.statement_type,
        fiscal_year=base_statement_version.fiscal_year,
        fiscal_period=base_statement_version.fiscal_period,
        version_sequence=base_statement_version.version_sequence,
        gaap_concept="us-gaap:Revenues",
        canonical_metric_code=None,
    )

    await use_case.execute(req)

    assert overrides_repo.list_all_rules_calls == 0
    assert len(overrides_repo.list_rules_for_concept_calls) == 1
    call = overrides_repo.list_rules_for_concept_calls[0]
    assert call["concept"] == "us-gaap:Revenues"
    assert call["taxonomy"] == "US_GAAP_2024"


# ---------------------------------------------------------------------------
# Tests: validation errors
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_execute_rejects_empty_cik(
    base_statement_version: FakeStatementVersion,
    base_observability: StatementOverrideObservability,
) -> None:
    """Empty CIK should raise EdgarMappingError."""
    statements_repo = FakeStatementsRepository(versions=[base_statement_version])
    overrides_repo = FakeOverridesRepository(rules=[])
    uow = FakeUnitOfWork(statements_repo=statements_repo, overrides_repo=overrides_repo)

    use_case = GetStatementOverrideTraceUseCase(uow=uow)
    use_case._observability_service = FakeObservabilityService(  # type: ignore[attr-defined]
        result=base_observability,
    )

    req = GetStatementOverrideTraceRequest(
        cik="  ",
        statement_type=base_statement_version.statement_type,
        fiscal_year=base_statement_version.fiscal_year,
        fiscal_period=base_statement_version.fiscal_period,
        version_sequence=base_statement_version.version_sequence,
    )

    with pytest.raises(EdgarMappingError):
        await use_case.execute(req)


@pytest.mark.asyncio
async def test_execute_rejects_non_positive_fiscal_year(
    base_statement_version: FakeStatementVersion,
    base_observability: StatementOverrideObservability,
) -> None:
    """Non-positive fiscal_year should raise EdgarMappingError."""
    statements_repo = FakeStatementsRepository(versions=[base_statement_version])
    overrides_repo = FakeOverridesRepository(rules=[])
    uow = FakeUnitOfWork(statements_repo=statements_repo, overrides_repo=overrides_repo)

    use_case = GetStatementOverrideTraceUseCase(uow=uow)
    use_case._observability_service = FakeObservabilityService(  # type: ignore[attr-defined]
        result=base_observability,
    )

    req = GetStatementOverrideTraceRequest(
        cik=base_statement_version.cik,
        statement_type=base_statement_version.statement_type,
        fiscal_year=0,
        fiscal_period=base_statement_version.fiscal_period,
        version_sequence=base_statement_version.version_sequence,
    )

    with pytest.raises(EdgarMappingError):
        await use_case.execute(req)


@pytest.mark.asyncio
async def test_execute_invalid_canonical_metric_code_raises_mapping_error(
    base_statement_version: FakeStatementVersion,
    base_observability: StatementOverrideObservability,
) -> None:
    """Invalid canonical_metric_code should raise EdgarMappingError."""
    statements_repo = FakeStatementsRepository(versions=[base_statement_version])
    overrides_repo = FakeOverridesRepository(
        rules=[FakeMappingOverrideRule(base_metric=CanonicalStatementMetric.REVENUE)]
    )
    uow = FakeUnitOfWork(statements_repo=statements_repo, overrides_repo=overrides_repo)

    use_case = GetStatementOverrideTraceUseCase(uow=uow)
    use_case._observability_service = FakeObservabilityService(  # type: ignore[attr-defined]
        result=base_observability,
    )

    req = GetStatementOverrideTraceRequest(
        cik=base_statement_version.cik,
        statement_type=base_statement_version.statement_type,
        fiscal_year=base_statement_version.fiscal_year,
        fiscal_period=base_statement_version.fiscal_period,
        version_sequence=base_statement_version.version_sequence,
        canonical_metric_code="NOT_A_REAL_METRIC",
    )

    with pytest.raises(EdgarMappingError) as exc_info:
        await use_case.execute(req)

    err = exc_info.value
    assert isinstance(err, EdgarMappingError)
    assert getattr(err, "details", {}).get("canonical_metric_code") == "NOT_A_REAL_METRIC"


# ---------------------------------------------------------------------------
# Tests: ingestion errors
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_execute_raises_ingestion_error_when_no_versions_found(
    base_observability: StatementOverrideObservability,
) -> None:
    """No statement versions for the identity should raise EdgarIngestionError."""
    statements_repo = FakeStatementsRepository(versions=[])
    overrides_repo = FakeOverridesRepository(rules=[])
    uow = FakeUnitOfWork(statements_repo=statements_repo, overrides_repo=overrides_repo)

    use_case = GetStatementOverrideTraceUseCase(uow=uow)
    use_case._observability_service = FakeObservabilityService(  # type: ignore[attr-defined]
        result=base_observability,
    )

    req = GetStatementOverrideTraceRequest(
        cik="0000320193",
        statement_type=StatementType.INCOME_STATEMENT,
        fiscal_year=2024,
        fiscal_period=FiscalPeriod.FY,
        version_sequence=1,
    )

    with pytest.raises(EdgarIngestionError):
        await use_case.execute(req)


@pytest.mark.asyncio
async def test_execute_raises_ingestion_error_when_version_sequence_missing(
    base_statement_version: FakeStatementVersion,
    base_observability: StatementOverrideObservability,
) -> None:
    """Missing version_sequence for identity should raise EdgarIngestionError."""
    # Only version_sequence=2 exists; request 3.
    statements_repo = FakeStatementsRepository(versions=[base_statement_version])
    overrides_repo = FakeOverridesRepository(rules=[])
    uow = FakeUnitOfWork(statements_repo=statements_repo, overrides_repo=overrides_repo)

    use_case = GetStatementOverrideTraceUseCase(uow=uow)
    use_case._observability_service = FakeObservabilityService(  # type: ignore[attr-defined]
        result=base_observability,
    )

    req = GetStatementOverrideTraceRequest(
        cik=base_statement_version.cik,
        statement_type=base_statement_version.statement_type,
        fiscal_year=base_statement_version.fiscal_year,
        fiscal_period=base_statement_version.fiscal_period,
        version_sequence=3,
    )

    with pytest.raises(EdgarIngestionError):
        await use_case.execute(req)


@pytest.mark.asyncio
async def test_execute_raises_ingestion_error_when_no_normalized_payload(
    base_statement_version: FakeStatementVersion,
    base_observability: StatementOverrideObservability,
) -> None:
    """If the target version has no normalized_payload, raise EdgarIngestionError."""
    version_without_payload = FakeStatementVersion(
        cik=base_statement_version.cik,
        statement_type=base_statement_version.statement_type,
        accounting_standard=base_statement_version.accounting_standard,
        statement_date=base_statement_version.statement_date,
        fiscal_year=base_statement_version.fiscal_year,
        fiscal_period=base_statement_version.fiscal_period,
        currency=base_statement_version.currency,
        accession_id=base_statement_version.accession_id,
        version_sequence=base_statement_version.version_sequence,
        normalized_payload=None,
    )

    statements_repo = FakeStatementsRepository(versions=[version_without_payload])
    overrides_repo = FakeOverridesRepository(rules=[])
    uow = FakeUnitOfWork(statements_repo=statements_repo, overrides_repo=overrides_repo)

    use_case = GetStatementOverrideTraceUseCase(uow=uow)
    use_case._observability_service = FakeObservabilityService(  # type: ignore[attr-defined]
        result=base_observability,
    )

    req = GetStatementOverrideTraceRequest(
        cik=version_without_payload.cik,
        statement_type=version_without_payload.statement_type,
        fiscal_year=version_without_payload.fiscal_year,
        fiscal_period=version_without_payload.fiscal_period,
        version_sequence=version_without_payload.version_sequence,
    )

    with pytest.raises(EdgarIngestionError):
        await use_case.execute(req)
