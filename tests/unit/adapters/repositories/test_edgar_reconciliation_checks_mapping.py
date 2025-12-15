# tests/unit/adapters/repositories/test_edgar_reconciliation_checks_mapping.py
"""Unit tests for reconciliation result → ledger row mapping.

Purpose:
    Verify deterministic and correct mapping from the domain ReconciliationResult
    entity into the persistence payload used by the SQLAlchemy repository.

Layer:
    tests/unit
"""

from __future__ import annotations

from datetime import UTC, datetime
from decimal import Decimal
from uuid import uuid4

from arche_api.adapters.repositories.edgar_reconciliation_checks_repository import (
    SqlAlchemyEdgarReconciliationChecksRepository,
)
from arche_api.domain.entities.edgar_dq import NormalizedStatementIdentity
from arche_api.domain.entities.edgar_reconciliation import ReconciliationResult
from arche_api.domain.enums.edgar import FiscalPeriod, MaterialityClass, StatementType
from arche_api.domain.enums.edgar_reconciliation import (
    ReconciliationRuleCategory,
    ReconciliationStatus,
)


def test_to_row_dict_maps_core_fields() -> None:
    """Map core identity/rule/outcome fields into an insertable row dict."""
    identity = NormalizedStatementIdentity(
        cik="0000320193",
        statement_type=StatementType.BALANCE_SHEET,
        fiscal_year=2024,
        fiscal_period=FiscalPeriod.FY,
        version_sequence=1,
    )

    result = ReconciliationResult(
        statement_identity=identity,
        rule_id="BS_ASSETS_EQ_LIAB_EQUITY",
        rule_category=ReconciliationRuleCategory.IDENTITY,
        status=ReconciliationStatus.FAIL,
        severity=MaterialityClass.HIGH,
        expected_value=Decimal("100"),
        actual_value=Decimal("90"),
        delta=Decimal("-10"),
        dimension_key="segment:consolidated",
        dimension_labels={"segment": "Consolidated"},
        notes={"tolerance": "0.01"},
    )

    row = SqlAlchemyEdgarReconciliationChecksRepository._to_row_dict(  # noqa: SLF001
        result=result,
        reconciliation_run_id=uuid4(),
        executed_at=datetime(2025, 12, 12, tzinfo=UTC),
        statement_version_id=uuid4(),
        company_id=uuid4(),
        statement_date=None,
    )

    assert row["cik"] == "0000320193"
    assert row["statement_type"] == StatementType.BALANCE_SHEET.value
    assert row["fiscal_year"] == 2024
    assert row["fiscal_period"] == FiscalPeriod.FY.value
    assert row["version_sequence"] == 1

    assert row["rule_id"] == "BS_ASSETS_EQ_LIAB_EQUITY"
    assert row["rule_category"] == ReconciliationRuleCategory.IDENTITY.value
    assert row["status"] == ReconciliationStatus.FAIL.value
    assert row["expected_value"] == Decimal("100")
    assert row["actual_value"] == Decimal("90")
    assert row["delta_value"] == Decimal("-10")
    assert row["dimension_key"] == "segment:consolidated"
    assert row["dimension_labels"] == {"segment": "Consolidated"}
    assert row["notes"] == {"tolerance": "0.01"}
