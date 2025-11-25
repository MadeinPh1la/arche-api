# src/stacklion_api/domain/entities/canonical_statement_payload.py
# Copyright (c) Stacklion.
# SPDX-License-Identifier: MIT
"""
Canonical normalized statement payload.

Purpose:
    Define a provider-agnostic, modeling-ready representation of financial
    statements that EDGAR XBRL (US GAAP / IFRS) and other providers normalize
    into. This is the central value object used by the Normalized Statement
    Payload Engine and downstream modeling use cases.

Layer:
    domain

Notes:
    - This type is intentionally transport-agnostic (no Pydantic, no HTTP).
    - Numeric values use `Decimal` in the domain and should be serialized as
      strings on the wire to preserve precision.
    - All amounts are normalized to full reporting units (no "in thousands"
      ambiguity). The `unit_multiplier` field is fixed at 0 for normalized
      payloads produced by the engine in E6-F.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from datetime import date
from decimal import Decimal

from stacklion_api.domain.enums.canonical_statement_metric import (
    CanonicalStatementMetric,
)
from stacklion_api.domain.enums.edgar import (
    AccountingStandard,
    FiscalPeriod,
    StatementType,
)


@dataclass(frozen=True)
class CanonicalStatementPayload:
    """Canonical normalized financial statement payload.

    Attributes:
        cik:
            Company CIK associated with this statement.
        statement_type:
            Type of statement (e.g., INCOME_STATEMENT, BALANCE_SHEET,
            CASH_FLOW_STATEMENT).
        accounting_standard:
            Accounting standard used (e.g., US_GAAP, IFRS).
        statement_date:
            Reporting period end date for the statement.
        fiscal_year:
            Fiscal year associated with the statement.
        fiscal_period:
            Fiscal period (e.g., FY, Q1, Q2).
        currency:
            ISO currency code for reported values (e.g., "USD").
        unit_multiplier:
            Scaling factor applied to the reported amounts. For normalized
            payloads produced by the E6-F engine, this MUST be 0, meaning
            all values are in full reporting units.
        core_metrics:
            Mapping of canonical metrics that are part of the core modeling
            vocabulary (e.g., REVENUE, NET_INCOME, TOTAL_ASSETS) to their
            normalized values.
        extra_metrics:
            Mapping for long-tail or company-specific metrics that do not
            have stable canonical identifiers yet but are still useful for
            advanced modeling. Keys should be stable, descriptive strings.
        dimensions:
            Simple dimensional tags describing the statement context, such as:
                - "consolidation": "CONSOLIDATED"
                - "operations": "CONTINUING"
            E6-F focuses on consolidated primary statements; segment /
            geographic breakdowns can be introduced in later phases.
        source_accession_id:
            EDGAR accession ID for the filing that produced this payload.
        source_taxonomy:
            Textual identifier of the taxonomy version used, such as
            "US_GAAP_2024" or "IFRS_2023".
        source_version_sequence:
            Version sequence from the underlying StatementVersion that this
            payload was derived from.
    """

    cik: str
    statement_type: StatementType
    accounting_standard: AccountingStandard
    statement_date: date
    fiscal_year: int
    fiscal_period: FiscalPeriod
    currency: str
    unit_multiplier: int

    core_metrics: Mapping[CanonicalStatementMetric, Decimal]
    extra_metrics: Mapping[str, Decimal]
    dimensions: Mapping[str, str]

    source_accession_id: str
    source_taxonomy: str
    source_version_sequence: int


__all__ = ["CanonicalStatementPayload"]
