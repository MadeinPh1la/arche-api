# Copyright (c)
# SPDX-License-Identifier: MIT
"""HTTP schemas for EDGAR reconciliation endpoints (v1).

Layer:
    adapters/schemas/http
"""

from __future__ import annotations

from datetime import datetime
from decimal import Decimal
from typing import Any

from pydantic import BaseModel, ConfigDict, Field

from arche_api.domain.enums.edgar_reconciliation import (
    ReconciliationRuleCategory,
    ReconciliationStatus,
)


class RunReconciliationRequestHTTP(BaseModel):
    """Request body for POST /v1/edgar/reconciliation/run."""

    model_config = ConfigDict(extra="forbid")

    cik: str = Field(..., description="Company CIK as digits-only string.", examples=["0000320193"])
    statement_type: str = Field(
        ...,
        description="Anchor statement type (StatementType.value). Reconciliation runs across IS/BS/CF.",
        examples=["INCOME_STATEMENT"],
    )
    fiscal_year: int = Field(..., ge=1, description="Fiscal year associated with the statement.")
    fiscal_period: str = Field(
        ..., description="Fiscal period (FiscalPeriod.value).", examples=["FY"]
    )
    rule_categories: list[ReconciliationRuleCategory] | None = Field(
        default=None,
        description="Optional subset of rule categories to run.",
        examples=[["IDENTITY", "CALENDAR"]],
    )
    deep: bool = Field(
        default=False,
        description="When true, load fact-level detail for rules that need it (segment/FX).",
        examples=[False],
    )
    fiscal_year_window: int = Field(
        default=0,
        ge=0,
        le=20,
        description="Inclusive fiscal-year window size. 0 means only the requested year.",
        examples=[0, 2],
    )


class ReconciliationResultHTTP(BaseModel):
    """Single reconciliation rule evaluation result in HTTP form."""

    model_config = ConfigDict(extra="forbid")

    cik: str = Field(..., description="Company CIK.")
    statement_type: str = Field(..., description="Statement type for the evaluated identity.")
    fiscal_year: int = Field(..., description="Fiscal year for the evaluated identity.")
    fiscal_period: str = Field(..., description="Fiscal period for the evaluated identity.")
    version_sequence: int = Field(
        ..., description="Statement version sequence for the evaluated identity."
    )

    rule_id: str = Field(..., description="Stable reconciliation rule identifier.")
    rule_category: ReconciliationRuleCategory = Field(..., description="Rule category.")
    status: ReconciliationStatus = Field(..., description="Evaluation outcome.")
    severity: str = Field(..., description="Severity (MaterialityClass aligned).")

    expected_value: Decimal | None = Field(None, description="Expected value under the rule.")
    actual_value: Decimal | None = Field(None, description="Actual observed value.")
    delta: Decimal | None = Field(None, description="Actual - expected.")
    dimension_key: str | None = Field(
        None, description="Dimension key when rule is dimension-specific."
    )
    dimension_labels: dict[str, str] | None = Field(
        None, description="Dimension labels when applicable."
    )
    notes: dict[str, Any] | None = Field(None, description="Machine-readable diagnostic payload.")


class RunReconciliationResponseHTTP(BaseModel):
    """Response payload for a reconciliation run."""

    model_config = ConfigDict(extra="forbid")

    reconciliation_run_id: str = Field(..., description="UUID for the reconciliation run.")
    executed_at: datetime = Field(..., description="UTC timestamp at which the run completed.")
    results: list[ReconciliationResultHTTP] = Field(
        ..., description="Deterministically ordered results."
    )


class LedgerQueryHTTP(BaseModel):
    """Query model for reconciliation ledger reads (used for documentation/clients)."""

    model_config = ConfigDict(extra="forbid")

    cik: str = Field(..., description="Company CIK as digits-only string.", examples=["0000320193"])
    statement_type: str = Field(
        ..., description="Statement type (StatementType.value).", examples=["BALANCE_SHEET"]
    )
    fiscal_year: int = Field(..., ge=1, description="Fiscal year.")
    fiscal_period: str = Field(
        ..., description="Fiscal period (FiscalPeriod.value).", examples=["FY"]
    )
    version_sequence: int = Field(..., ge=1, description="Statement version sequence.")

    reconciliation_run_id: str | None = Field(
        None, description="Optional run UUID to restrict results."
    )
    rule_category: ReconciliationRuleCategory | None = Field(
        None, description="Optional category filter."
    )
    statuses: list[ReconciliationStatus] | None = Field(None, description="Optional status filter.")
    limit: int | None = Field(None, ge=1, le=20000, description="Optional maximum rows to return.")


class ReconciliationSummaryQueryHTTP(BaseModel):
    """Query model for reconciliation summary reads (used for documentation/clients)."""

    model_config = ConfigDict(extra="forbid")

    cik: str = Field(..., description="Company CIK.")
    statement_type: str = Field(..., description="Statement type (StatementType.value).")
    fiscal_year_from: int = Field(..., ge=1, description="Inclusive start fiscal year.")
    fiscal_year_to: int = Field(..., ge=1, description="Inclusive end fiscal year.")
    rule_category: ReconciliationRuleCategory | None = Field(
        None, description="Optional category filter."
    )
    limit: int = Field(
        default=5000, ge=1, le=50000, description="Maximum rows to read from ledger."
    )


class ReconciliationSummaryBucketHTTP(BaseModel):
    """Aggregated PASS/WARN/FAIL counts for a fiscal period and rule category."""

    model_config = ConfigDict(extra="forbid")

    fiscal_year: int = Field(..., description="Fiscal year.")
    fiscal_period: str = Field(..., description="Fiscal period (FiscalPeriod.value).")
    version_sequence: int = Field(..., description="Statement version sequence.")
    rule_category: ReconciliationRuleCategory = Field(..., description="Rule category.")
    pass_count: int = Field(..., ge=0, description="Number of PASS results.")
    warn_count: int = Field(..., ge=0, description="Number of WARN results.")
    fail_count: int = Field(..., ge=0, description="Number of FAIL results.")
