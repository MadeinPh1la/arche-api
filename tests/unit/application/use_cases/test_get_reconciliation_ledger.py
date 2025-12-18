from __future__ import annotations

from decimal import Decimal
from typing import Any

import pytest

from arche_api.application.schemas.dto.reconciliation import GetReconciliationLedgerRequestDTO
from arche_api.application.use_cases.reconciliation.get_reconciliation_ledger import (
    GetReconciliationLedgerUseCase,
)
from arche_api.domain.entities.edgar_dq import NormalizedStatementIdentity
from arche_api.domain.entities.edgar_reconciliation import ReconciliationResult
from arche_api.domain.enums.edgar import FiscalPeriod, MaterialityClass, StatementType
from arche_api.domain.enums.edgar_reconciliation import (
    ReconciliationRuleCategory,
    ReconciliationStatus,
)


class _FakeLedgerRepo:
    def __init__(self, rows: list[ReconciliationResult]) -> None:
        self._rows = rows

    async def list_for_statement(
        self,
        *,
        identity: Any,
        reconciliation_run_id: Any = None,
        limit: Any = None,
    ) -> list[ReconciliationResult]:
        return self._rows


class _FakeUow:
    def __init__(self, repo: _FakeLedgerRepo) -> None:
        self.reconciliation_checks_repo = repo

    async def __aenter__(self) -> Any:
        return self

    async def __aexit__(self, exc_type: Any, exc: Any, tb: Any) -> None:
        return None


@pytest.mark.asyncio
async def test_get_reconciliation_ledger_filters_category_and_status() -> None:
    identity = NormalizedStatementIdentity(
        cik="0000000001",
        statement_type=StatementType.BALANCE_SHEET,
        fiscal_year=2024,
        fiscal_period=FiscalPeriod.FY,
        version_sequence=1,
    )

    rows = [
        ReconciliationResult(
            statement_identity=identity,
            rule_id="r1",
            rule_category=ReconciliationRuleCategory.IDENTITY,
            status=ReconciliationStatus.PASS,
            severity=MaterialityClass.LOW,
            expected_value=Decimal("1"),
            actual_value=Decimal("1"),
            delta=Decimal("0"),
            dimension_key=None,
            dimension_labels=None,
            notes=None,
        ),
        ReconciliationResult(
            statement_identity=identity,
            rule_id="r2",
            rule_category=ReconciliationRuleCategory.ROLLFORWARD,
            status=ReconciliationStatus.FAIL,
            severity=MaterialityClass.HIGH,
            expected_value=None,
            actual_value=None,
            delta=None,
            dimension_key=None,
            dimension_labels=None,
            notes=None,
        ),
    ]

    uow = _FakeUow(_FakeLedgerRepo(rows))
    uc = GetReconciliationLedgerUseCase(uow=uow)  # type: ignore[arg-type]

    res = await uc.execute(
        GetReconciliationLedgerRequestDTO(
            identity=identity,
            reconciliation_run_id=None,
            rule_category=ReconciliationRuleCategory.IDENTITY,
            statuses=(ReconciliationStatus.PASS,),
            limit=None,
        )
    )

    assert res.identity == identity
    assert len(res.items) == 1
    assert res.items[0].result.rule_id == "r1"
