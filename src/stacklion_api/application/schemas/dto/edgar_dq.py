# src/stacklion_api/application/schemas/dto/edgar_dq.py
# Copyright (c)
# SPDX-License-Identifier: MIT
"""Application DTOs for EDGAR fact store and data-quality overlays.

Purpose:
    Provide strict Pydantic DTOs for:
        * Persistent normalized facts derived from canonical statement payloads.
        * Fact-level data-quality evaluations.
        * Rule-level DQ anomalies.
        * Statement-level DQ overlays combining facts + quality + anomalies.

Layer:
    application/schemas/dto

Notes:
    - These DTOs are transport-agnostic and suitable for mapping into HTTP
      schemas and envelopes in the adapters layer.
    - Decimal values are represented as strings to avoid precision loss.
"""

from __future__ import annotations

from datetime import date, datetime

from pydantic import ConfigDict

from stacklion_api.application.schemas.dto.base import BaseDTO
from stacklion_api.domain.enums.edgar import (
    AccountingStandard,
    FiscalPeriod,
    MaterialityClass,
    StatementType,
)


class NormalizedFactDTO(BaseDTO):
    """DTO representing a single normalized fact from the fact store."""

    model_config = ConfigDict(extra="forbid")

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

    value: str

    dimension_key: str
    dimensions: dict[str, str]
    source_line_item: str | None


class FactQualityDTO(BaseDTO):
    """DTO representing fact-level data-quality evaluation."""

    model_config = ConfigDict(extra="forbid")

    cik: str
    statement_type: StatementType
    fiscal_year: int
    fiscal_period: FiscalPeriod
    version_sequence: int

    metric_code: str
    dimension_key: str

    severity: MaterialityClass

    is_present: bool
    is_non_negative: bool | None
    is_consistent_with_history: bool | None
    has_known_issue: bool

    details: dict[str, str] | None = None


class DQAnomalyDTO(BaseDTO):
    """DTO representing a rule-level DQ anomaly."""

    model_config = ConfigDict(extra="forbid")

    dq_run_id: str
    metric_code: str | None
    dimension_key: str | None
    rule_code: str
    severity: MaterialityClass
    message: str
    details: dict[str, str] | None = None


class StatementDQOverlayDTO(BaseDTO):
    """DTO representing a statement-level DQ overlay."""

    model_config = ConfigDict(extra="forbid")

    cik: str
    statement_type: StatementType
    fiscal_year: int
    fiscal_period: FiscalPeriod
    version_sequence: int

    accounting_standard: AccountingStandard
    statement_date: date
    currency: str

    dq_run_id: str | None = None
    dq_rule_set_version: str | None = None
    dq_executed_at: datetime | None = None
    max_severity: MaterialityClass | None = None

    facts: list[NormalizedFactDTO]
    fact_quality: list[FactQualityDTO]
    anomalies: list[DQAnomalyDTO]


class PersistNormalizedFactsResultDTO(BaseDTO):
    """DTO representing the result of persisting facts for a statement."""

    model_config = ConfigDict(extra="forbid")

    cik: str
    statement_type: StatementType
    fiscal_year: int
    fiscal_period: FiscalPeriod
    version_sequence: int
    facts_persisted: int


class RunStatementDQResultDTO(BaseDTO):
    """DTO representing the result of running data-quality for a statement."""

    model_config = ConfigDict(extra="forbid")

    dq_run_id: str
    cik: str
    statement_type: StatementType
    fiscal_year: int
    fiscal_period: FiscalPeriod
    version_sequence: int

    rule_set_version: str
    scope_type: str
    history_lookback: int | None

    executed_at: datetime

    facts_evaluated: int
    anomaly_count: int
    max_severity: MaterialityClass | None


__all__ = [
    "NormalizedFactDTO",
    "FactQualityDTO",
    "DQAnomalyDTO",
    "StatementDQOverlayDTO",
    "PersistNormalizedFactsResultDTO",
    "RunStatementDQResultDTO",
]
