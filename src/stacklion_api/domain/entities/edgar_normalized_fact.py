# src/stacklion_api/domain/entities/edgar_normalized_fact.py
# Copyright (c) Stacklion.
# SPDX-License-Identifier: MIT
"""EDGAR normalized fact entity.

Purpose:
    Represent the atomic, modeling-ready "fact" derived from a canonical
    normalized EDGAR statement payload. This is the unit that the persistent
    fact store manages and that the data-quality engine evaluates.

Layer:
    domain/entities

Notes:
    - This entity is storage-agnostic and does not depend on SQLAlchemy or
      other infrastructure concerns.
    - Numeric values are represented as Decimal to avoid precision loss.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from datetime import date
from decimal import Decimal

from stacklion_api.domain.enums.edgar import AccountingStandard, FiscalPeriod, StatementType

__all__ = ["EdgarNormalizedFact"]


@dataclass(frozen=True, slots=True)
class EdgarNormalizedFact:
    """Atomic normalized EDGAR fact.

    Attributes:
        cik:
            Central Index Key for the filer.
        statement_type:
            Statement type (income statement, balance sheet, cash flow, etc.).
        accounting_standard:
            Accounting standard used (e.g., US_GAAP, IFRS).
        fiscal_year:
            Fiscal year associated with the statement (>= 1).
        fiscal_period:
            Fiscal period within the year (e.g., FY, Q1, Q2).
        statement_date:
            Reporting period end date.
        version_sequence:
            Statement version sequence from the canonical payload identity.
        metric_code:
            Canonical metric code (e.g., "REVENUE", "NET_INCOME").
        metric_label:
            Optional human-readable label for the metric, when available.
        unit:
            Unit code for the metric value, typically ISO 4217 (e.g., "USD").
        period_start:
            Inclusive start date of the fact's reporting period, when known.
            May be None when the start date is not explicitly modeled.
        period_end:
            Inclusive end date of the fact's reporting period.
        value:
            Decimal value in full units, suitable for analytics and modeling.
        dimensions:
            Simple dimensional context for the fact, such as {"segment": "US"}.
            Keys and values must be strings and are assumed to be normalized.
        dimension_key:
            Deterministic, normalized key derived from ``dimensions`` used to
            uniquely identify the dimensional slice (e.g., a stable hash or
            canonicalized string representation).
        source_line_item:
            Optional source line-item label from the filing, when available.
    """

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

    value: Decimal

    dimensions: Mapping[str, str]
    dimension_key: str

    source_line_item: str | None

    def __post_init__(self) -> None:
        """Hook for enforcing invariants on normalized facts.

        Implemented as a no-op to satisfy domain-entity conventions without
        altering existing behavior. This method can be extended later with
        stricter validation if required by the analytics layer.
        """
        return
