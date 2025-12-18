from __future__ import annotations

from typing import Any

import pytest

from arche_api.application.schemas.dto.reconciliation import GetReconciliationSummaryRequestDTO
from arche_api.application.use_cases.reconciliation.get_reconciliation_summary import (
    GetReconciliationSummaryUseCase,
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

    async def list_for_window(
        self,
        *,
        cik: str,
        statement_type: str,
        fiscal_year_from: int,
        fiscal_year_to: int,
        limit: int = 5000,
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
async def test_get_reconciliation_summary_aggregates_buckets() -> None:
    ident_2024 = NormalizedStatementIdentity(
        cik="0000320193",
        statement_type=StatementType.BALANCE_SHEET,
        fiscal_year=2024,
        fiscal_period=FiscalPeriod.FY,
        version_sequence=1,
    )

    rows = [
        ReconciliationResult(
            statement_identity=ident_2024,
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
        ReconciliationResult(
            statement_identity=ident_2024,
            rule_id="r2",
            rule_category=ReconciliationRuleCategory.IDENTITY,
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
    uc = GetReconciliationSummaryUseCase(uow=uow)  # type: ignore[arg-type]

    res = await uc.execute(
        GetReconciliationSummaryRequestDTO(
            cik="0000320193",
            statement_type="BALANCE_SHEET",
            fiscal_year_from=2024,
            fiscal_year_to=2024,
            rule_category=None,
            limit=5000,
        )
    )

    assert res.cik == "0000320193"
    assert res.statement_type == "BALANCE_SHEET"
    assert len(res.buckets) == 1
    b = res.buckets[0]
    assert b.fiscal_year == 2024
    assert b.fiscal_period == "FY"
    assert b.version_sequence == 1
    assert b.rule_category == ReconciliationRuleCategory.IDENTITY
    assert b.pass_count == 1
    assert b.fail_count == 1
