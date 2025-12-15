# src/arche_api/application/schemas/dto/edgar_derived.py
# Copyright (c) Arche.
# SPDX-License-Identifier: MIT
"""Application DTOs for EDGAR-derived metrics.

Purpose:
    Provide Pydantic DTOs for derived metrics time series built on top of
    canonical normalized EDGAR payloads. These DTOs are transport-agnostic
    and suitable for mapping into HTTP schemas and envelopes.

Layer:
    application/schemas/dto
"""

from __future__ import annotations

from datetime import date

from pydantic import ConfigDict

from arche_api.application.schemas.dto.base import BaseDTO
from arche_api.domain.enums.derived_metric import DerivedMetric
from arche_api.domain.enums.edgar import AccountingStandard, FiscalPeriod, StatementType


class EdgarDerivedMetricsPointDTO(BaseDTO):
    """DTO representing a single derived metrics time-series point.

    Attributes:
        cik: Company CIK.
        statement_type: Primary statement type for the derived metrics.
        accounting_standard: Accounting standard (e.g., US_GAAP, IFRS).
        statement_date: Reporting period end date.
        fiscal_year: Fiscal year associated with the statement (>= 1).
        fiscal_period: Fiscal period (e.g., FY, Q1, Q2).
        currency: ISO 4217 currency code (e.g., "USD").
        metrics: Mapping from derived metric codes to decimal string values.
        normalized_payload_version_sequence:
            Version sequence of the canonical normalized payload used as the
            basis for this derived metrics point.
    """

    model_config = ConfigDict(extra="forbid")

    cik: str
    statement_type: StatementType
    accounting_standard: AccountingStandard
    statement_date: date
    fiscal_year: int
    fiscal_period: FiscalPeriod
    currency: str
    metrics: dict[DerivedMetric, str]
    normalized_payload_version_sequence: int


__all__ = ["EdgarDerivedMetricsPointDTO"]
