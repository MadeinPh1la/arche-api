# src/stacklion_api/domain/enums/edgar.py
# Copyright (c) Stacklion.
# SPDX-License-Identifier: MIT
"""
EDGAR-specific enumerations.

Purpose:
    Provide provider-agnostic enums for EDGAR filings and financial statements.
    Normalize SEC form codes and statement taxonomy into a stable internal model.

Layer:
    domain

Notes:
    - Adapters are responsible for mapping raw SEC/XBRL codes into these enums.
    - Keep this set intentionally small and modeling-focused; avoid SEC form
      explosion.
"""

from __future__ import annotations

from enum import Enum


class FilingType(str, Enum):
    """Supported EDGAR filing types.

    Values are normalized, provider-agnostic tokens rather than raw SEC form codes.
    """

    FORM_10K = "10-K"
    FORM_10Q = "10-Q"
    FORM_8K = "8-K"
    FORM_20F = "20-F"
    FORM_40F = "40-F"
    FORM_6K = "6-K"
    REG_S1 = "S-1"
    REG_S3 = "S-3"
    OTHER = "OTHER"


class StatementType(str, Enum):
    """Supported financial statement types.

    These are intentionally coarse and modeling-oriented. More granular breakdowns
    (e.g., "INCOME_STATEMENT_Q1") are encoded via fiscal period metadata, not enum
    explosion.
    """

    INCOME_STATEMENT = "INCOME_STATEMENT"
    BALANCE_SHEET = "BALANCE_SHEET"
    CASH_FLOW_STATEMENT = "CASH_FLOW_STATEMENT"


class AccountingStandard(str, Enum):
    """Accounting standards used in EDGAR filings."""

    US_GAAP = "US_GAAP"
    IFRS = "IFRS"
    OTHER = "OTHER"


class FiscalPeriod(str, Enum):
    """Fiscal period for a given statement version.

    Examples:
        FY: Full year
        Q1, Q2, Q3, Q4: Quarterly
        H1: First half, if applicable.
    """

    FY = "FY"
    Q1 = "Q1"
    Q2 = "Q2"
    Q3 = "Q3"
    Q4 = "Q4"
    H1 = "H1"
    OTHER = "OTHER"
