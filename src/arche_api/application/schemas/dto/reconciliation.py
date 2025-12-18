# Copyright (c)
# SPDX-License-Identifier: MIT
"""Application DTOs for EDGAR reconciliation flows.

Purpose:
    Provide application-layer DTOs used by reconciliation use-cases.
    These DTOs are transport-agnostic and are mapped to HTTP schemas by
    presenters.

Layer:
    application/schemas/dto
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal
from typing import Any

from arche_api.domain.entities.edgar_dq import NormalizedStatementIdentity
from arche_api.domain.enums.edgar_reconciliation import (
    ReconciliationRuleCategory,
    ReconciliationStatus,
)


@dataclass(frozen=True, slots=True)
class RunReconciliationOptionsDTO:
    """Options controlling reconciliation execution.

    Attributes:
        rule_categories:
            Optional categories to run. When None, runs all available rules.
        deep:
            When True, load fact-level detail (for segment/FX rules) where
            available; when False, run payload-only checks.
        fiscal_year_window:
            Optional window (inclusive) of fiscal years to include in the run.
            For example, 2 means [fiscal_year-2 .. fiscal_year].
    """

    rule_categories: tuple[ReconciliationRuleCategory, ...] | None = None
    deep: bool = False
    fiscal_year_window: int = 0


@dataclass(frozen=True, slots=True)
class RunReconciliationRequestDTO:
    """Request DTO for running reconciliation."""

    cik: str
    statement_type: str
    fiscal_year: int
    fiscal_period: str
    options: RunReconciliationOptionsDTO = RunReconciliationOptionsDTO()


@dataclass(frozen=True, slots=True)
class ReconciliationResultDTO:
    """Application-projected reconciliation result."""

    statement_identity: NormalizedStatementIdentity
    rule_id: str
    rule_category: ReconciliationRuleCategory
    status: ReconciliationStatus
    severity: str
    expected_value: Decimal | None
    actual_value: Decimal | None
    delta: Decimal | None
    dimension_key: str | None
    dimension_labels: Mapping[str, str] | None
    notes: Mapping[str, Any] | None


@dataclass(frozen=True, slots=True)
class RunReconciliationResponseDTO:
    """Response DTO for a reconciliation run."""

    reconciliation_run_id: str
    executed_at: datetime
    results: tuple[ReconciliationResultDTO, ...]


@dataclass(frozen=True, slots=True)
class GetReconciliationLedgerRequestDTO:
    """Request DTO for statement-scoped reconciliation ledger reads."""

    identity: NormalizedStatementIdentity
    reconciliation_run_id: str | None = None
    rule_category: ReconciliationRuleCategory | None = None
    statuses: tuple[ReconciliationStatus, ...] | None = None
    limit: int | None = None


@dataclass(frozen=True, slots=True)
class ReconciliationLedgerEntryDTO:
    """Timeline-style ledger entry for a statement identity.

    Notes:
        The underlying storage is append-only and ordered by executed_at.
        This DTO surfaces that sequence deterministically.
    """

    executed_at: datetime | None
    result: ReconciliationResultDTO


@dataclass(frozen=True, slots=True)
class GetReconciliationLedgerResponseDTO:
    """Response DTO for statement-scoped ledger reads."""

    identity: NormalizedStatementIdentity
    items: tuple[ReconciliationLedgerEntryDTO, ...]


@dataclass(frozen=True, slots=True)
class ReconciliationSummaryBucketDTO:
    """Aggregated reconciliation summary bucket."""

    fiscal_year: int
    fiscal_period: str
    version_sequence: int
    rule_category: ReconciliationRuleCategory
    pass_count: int
    warn_count: int
    fail_count: int


@dataclass(frozen=True, slots=True)
class GetReconciliationSummaryRequestDTO:
    """Request DTO for reconciliation summary over a multi-year window."""

    cik: str
    statement_type: str
    fiscal_year_from: int
    fiscal_year_to: int
    rule_category: ReconciliationRuleCategory | None = None
    limit: int = 5000


@dataclass(frozen=True, slots=True)
class GetReconciliationSummaryResponseDTO:
    """Response DTO for reconciliation summary."""

    cik: str
    statement_type: str
    fiscal_year_from: int
    fiscal_year_to: int
    buckets: tuple[ReconciliationSummaryBucketDTO, ...]
