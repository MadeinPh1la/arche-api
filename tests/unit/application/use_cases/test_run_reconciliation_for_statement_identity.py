# tests/unit/application/use_cases/test_run_reconciliation_for_statement_identity.py
from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from datetime import date
from typing import Any

import pytest

from arche_api.application.schemas.dto.reconciliation import (
    RunReconciliationOptionsDTO,
    RunReconciliationRequestDTO,
)
from arche_api.application.use_cases.reconciliation.run_reconciliation_for_statement_identity import (
    RunReconciliationForStatementIdentityUseCase,
)
from arche_api.domain.entities.canonical_statement_payload import CanonicalStatementPayload
from arche_api.domain.entities.edgar_dq import NormalizedStatementIdentity
from arche_api.domain.entities.edgar_reconciliation import ReconciliationResult
from arche_api.domain.enums.edgar import FiscalPeriod, MaterialityClass, StatementType
from arche_api.domain.enums.edgar_reconciliation import (
    ReconciliationRuleCategory,
    ReconciliationStatus,
)


def _default_accounting_standard() -> Any:
    """Return a stable AccountingStandard value without hard-coding enum members.

    Notes:
        Some test environments evolve the AccountingStandard enum. We avoid brittle
        imports by selecting the first available enum member when present, and
        otherwise falling back to the common "US_GAAP" string used throughout the
        codebase.
    """
    mod = __import__("arche_api.domain.enums.edgar", fromlist=["AccountingStandard"])
    accounting_standard = getattr(mod, "AccountingStandard", None)
    if accounting_standard is None:
        return "US_GAAP"
    return next(iter(accounting_standard))


@dataclass(frozen=True, slots=True)
class _FakeStatementVersion:
    version_sequence: int
    normalized_payload: CanonicalStatementPayload | None


class _FakeStatementsRepo:
    """Statements repo test double.

    Important:
        The production use case reconciles across IS/BS/CF, so it queries multiple
        statement types. This fake returns versions only for the seeded payload's
        statement type to prevent accidental duplication (which would otherwise
        cause deep mode to load facts multiple times).
    """

    def __init__(self, *, payload: CanonicalStatementPayload, version_sequence: int = 1) -> None:
        self._payload = payload
        self._version_sequence = version_sequence

    async def list_statement_versions_for_company(
        self, *, cik: str, statement_type: Any, fiscal_year: int, fiscal_period: Any
    ) -> list[_FakeStatementVersion]:
        if statement_type != self._payload.statement_type:
            return []
        return [
            _FakeStatementVersion(
                version_sequence=self._version_sequence,
                normalized_payload=self._payload,
            )
        ]


class _FakeFactsRepo:
    def __init__(self) -> None:
        self.calls: list[NormalizedStatementIdentity] = []

    async def list_facts_for_statement(self, identity: NormalizedStatementIdentity) -> list[Any]:
        self.calls.append(identity)
        return []


class _FakeLedgerRepo:
    def __init__(self) -> None:
        self.append_calls: list[tuple[str, Any, Sequence[ReconciliationResult]]] = []

    async def append_results(
        self, *, reconciliation_run_id: str, executed_at: Any, results: Any
    ) -> None:
        self.append_calls.append((reconciliation_run_id, executed_at, results))

    async def list_for_statement(
        self, *, identity: Any, reconciliation_run_id: Any = None, limit: Any = None
    ) -> list[Any]:
        return []

    async def list_for_window(
        self,
        *,
        cik: Any,
        statement_type: Any,
        fiscal_year_from: Any,
        fiscal_year_to: Any,
        limit: int = 5000,
    ) -> list[Any]:
        return []


class _FakeUow:
    def __init__(self, statements_repo: Any, facts_repo: Any, ledger_repo: Any) -> None:
        self.statements_repo = statements_repo
        self.facts_repo = facts_repo
        self.reconciliation_checks_repo = ledger_repo
        self.committed = False

    async def __aenter__(self) -> Any:
        return self

    async def __aexit__(self, exc_type: Any, exc: Any, tb: Any) -> None:
        return None

    async def commit(self) -> None:
        self.committed = True

    async def rollback(self) -> None:
        return None

    def get_repository(self, repo_type: type[Any]) -> Any:
        raise AssertionError("use-case should prefer explicit fake attrs")


def _payload() -> CanonicalStatementPayload:
    """Build a minimal canonical payload matching the domain constructor."""
    return CanonicalStatementPayload(
        cik="0000000001",
        statement_type=StatementType.BALANCE_SHEET,
        fiscal_year=2024,
        fiscal_period=FiscalPeriod.FY,
        statement_date=date(2024, 12, 31),
        currency="USD",
        accounting_standard=_default_accounting_standard(),
        unit_multiplier=1,
        core_metrics={},
        extra_metrics={},
        dimensions={},
        source_version_sequence=1,
        source_taxonomy="us-gaap",
        source_accession_id="0000000001-24-000001",
    )


@pytest.mark.asyncio
async def test_run_reconciliation_shallow_persists_ledger() -> None:
    payload = _payload()
    statements_repo = _FakeStatementsRepo(payload=payload, version_sequence=1)
    facts_repo = _FakeFactsRepo()
    ledger_repo = _FakeLedgerRepo()
    uow = _FakeUow(statements_repo, facts_repo, ledger_repo)

    class _FakeEngine:
        def run(
            self, *, rules: Any, statements: Any, facts_by_identity: Any = None
        ) -> tuple[ReconciliationResult, ...]:
            identity = NormalizedStatementIdentity(
                cik="0000000001",
                statement_type=StatementType.BALANCE_SHEET,
                fiscal_year=2024,
                fiscal_period=FiscalPeriod.FY,
                version_sequence=1,
            )
            return (
                ReconciliationResult(
                    statement_identity=identity,
                    rule_id="r1",
                    rule_category=ReconciliationRuleCategory.IDENTITY,
                    status=ReconciliationStatus.PASS,
                    severity=MaterialityClass.LOW,
                    expected_value=None,
                    actual_value=None,
                    delta=None,
                    dimension_key=None,
                    dimension_labels=None,
                    notes=None,
                ),
            )

    use_case = RunReconciliationForStatementIdentityUseCase(uow=uow, engine=_FakeEngine())  # type: ignore[arg-type]
    res = await use_case.execute(
        RunReconciliationRequestDTO(
            cik="0000000001",
            statement_type="BALANCE_SHEET",
            fiscal_year=2024,
            fiscal_period="FY",
            options=RunReconciliationOptionsDTO(deep=False),
        )
    )

    assert uow.committed is True
    assert len(ledger_repo.append_calls) == 1
    assert res.reconciliation_run_id
    assert len(res.results) == 1
    assert facts_repo.calls == []


@pytest.mark.asyncio
async def test_run_reconciliation_deep_loads_facts() -> None:
    payload = _payload()
    statements_repo = _FakeStatementsRepo(payload=payload, version_sequence=1)
    facts_repo = _FakeFactsRepo()
    ledger_repo = _FakeLedgerRepo()
    uow = _FakeUow(statements_repo, facts_repo, ledger_repo)

    class _FakeEngine:
        def run(
            self, *, rules: Any, statements: Any, facts_by_identity: Any = None
        ) -> tuple[ReconciliationResult, ...]:
            return ()

    use_case = RunReconciliationForStatementIdentityUseCase(uow=uow, engine=_FakeEngine())  # type: ignore[arg-type]
    await use_case.execute(
        RunReconciliationRequestDTO(
            cik="0000000001",
            statement_type="BALANCE_SHEET",
            fiscal_year=2024,
            fiscal_period="FY",
            options=RunReconciliationOptionsDTO(deep=True),
        )
    )

    # With the statements repo fake scoped to a single statement type, deep mode
    # should load facts exactly once.
    assert len(facts_repo.calls) == 1
