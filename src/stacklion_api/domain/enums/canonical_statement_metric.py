# src/stacklion_api/domain/enums/canonical_statement_metric.py
# Copyright (c) Stacklion.
# SPDX-License-Identifier: MIT
"""
Canonical statement metrics enumeration.

Purpose:
    Define a stable, provider-agnostic set of canonical financial statement
    metrics used across normalized statement payloads. These metrics form the
    "spine" that EDGAR XBRL, IFRS, and any other provider taxonomies map into
    for modeling-ready financial statements.

Layer:
    domain

Notes:
    - Values are string identifiers suitable for use in JSON payloads and
      external contracts.
    - This enum focuses on high-value, commonly modeled metrics across:
        * Income Statement
        * Balance Sheet
        * Cash Flow Statement
      Additional metrics can be added in future versions in a strictly
      additive, backward-compatible manner.
"""

from __future__ import annotations

from enum import Enum


class CanonicalStatementMetric(str, Enum):
    """Canonical financial statement metrics.

    The enum names are UPPER_SNAKE_CASE and the values are the same strings,
    ensuring stable identifiers in JSON and other serialized forms.
    """

    # ------------------------------------------------------------------
    # Income Statement (Performance)
    # ------------------------------------------------------------------
    REVENUE = "REVENUE"
    COST_OF_REVENUE = "COST_OF_REVENUE"
    GROSS_PROFIT = "GROSS_PROFIT"

    RESEARCH_AND_DEVELOPMENT_EXPENSE = "RESEARCH_AND_DEVELOPMENT_EXPENSE"
    SELLING_GENERAL_AND_ADMINISTRATIVE_EXPENSE = "SELLING_GENERAL_AND_ADMINISTRATIVE_EXPENSE"
    DEPRECIATION_AND_AMORTIZATION_EXPENSE = "DEPRECIATION_AND_AMORTIZATION_EXPENSE"

    OPERATING_INCOME = "OPERATING_INCOME"
    OPERATING_EXPENSE = "OPERATING_EXPENSE"

    INTEREST_INCOME = "INTEREST_INCOME"
    INTEREST_EXPENSE = "INTEREST_EXPENSE"
    OTHER_NON_OPERATING_INCOME_EXPENSE = "OTHER_NON_OPERATING_INCOME_EXPENSE"

    INCOME_BEFORE_TAX = "INCOME_BEFORE_TAX"
    INCOME_TAX_EXPENSE = "INCOME_TAX_EXPENSE"
    NET_INCOME = "NET_INCOME"

    BASIC_EPS = "BASIC_EPS"
    DILUTED_EPS = "DILUTED_EPS"
    WEIGHTED_AVERAGE_SHARES_BASIC = "WEIGHTED_AVERAGE_SHARES_BASIC"
    WEIGHTED_AVERAGE_SHARES_DILUTED = "WEIGHTED_AVERAGE_SHARES_DILUTED"

    # ------------------------------------------------------------------
    # Balance Sheet (Position)
    # ------------------------------------------------------------------
    TOTAL_ASSETS = "TOTAL_ASSETS"
    TOTAL_CURRENT_ASSETS = "TOTAL_CURRENT_ASSETS"
    CASH_AND_CASH_EQUIVALENTS = "CASH_AND_CASH_EQUIVALENTS"
    SHORT_TERM_INVESTMENTS = "SHORT_TERM_INVESTMENTS"
    ACCOUNTS_RECEIVABLE_NET = "ACCOUNTS_RECEIVABLE_NET"
    INVENTORIES = "INVENTORIES"
    OTHER_CURRENT_ASSETS = "OTHER_CURRENT_ASSETS"

    TOTAL_NON_CURRENT_ASSETS = "TOTAL_NON_CURRENT_ASSETS"
    PROPERTY_PLANT_AND_EQUIPMENT_NET = "PROPERTY_PLANT_AND_EQUIPMENT_NET"
    GOODWILL = "GOODWILL"
    INTANGIBLE_ASSETS_NET = "INTANGIBLE_ASSETS_NET"
    OTHER_NON_CURRENT_ASSETS = "OTHER_NON_CURRENT_ASSETS"

    TOTAL_LIABILITIES = "TOTAL_LIABILITIES"
    TOTAL_CURRENT_LIABILITIES = "TOTAL_CURRENT_LIABILITIES"
    ACCOUNTS_PAYABLE = "ACCOUNTS_PAYABLE"
    SHORT_TERM_DEBT = "SHORT_TERM_DEBT"
    CURRENT_PORTION_OF_LONG_TERM_DEBT = "CURRENT_PORTION_OF_LONG_TERM_DEBT"
    OTHER_CURRENT_LIABILITIES = "OTHER_CURRENT_LIABILITIES"

    TOTAL_NON_CURRENT_LIABILITIES = "TOTAL_NON_CURRENT_LIABILITIES"
    LONG_TERM_DEBT = "LONG_TERM_DEBT"
    OTHER_NON_CURRENT_LIABILITIES = "OTHER_NON_CURRENT_LIABILITIES"

    TOTAL_EQUITY = "TOTAL_EQUITY"
    RETAINED_EARNINGS = "RETAINED_EARNINGS"
    ADDITIONAL_PAID_IN_CAPITAL = "ADDITIONAL_PAID_IN_CAPITAL"
    TREASURY_STOCK = "TREASURY_STOCK"
    ACCUMULATED_OTHER_COMPREHENSIVE_INCOME = "ACCUMULATED_OTHER_COMPREHENSIVE_INCOME"

    # ------------------------------------------------------------------
    # Cash Flow Statement (Flows)
    # ------------------------------------------------------------------
    NET_CASH_FROM_OPERATING_ACTIVITIES = "NET_CASH_FROM_OPERATING_ACTIVITIES"
    NET_CASH_FROM_INVESTING_ACTIVITIES = "NET_CASH_FROM_INVESTING_ACTIVITIES"
    NET_CASH_FROM_FINANCING_ACTIVITIES = "NET_CASH_FROM_FINANCING_ACTIVITIES"
    NET_INCREASE_DECREASE_IN_CASH = "NET_INCREASE_DECREASE_IN_CASH"

    CASH_PAID_FOR_INTEREST = "CASH_PAID_FOR_INTEREST"
    CASH_PAID_FOR_INCOME_TAXES = "CASH_PAID_FOR_INCOME_TAXES"

    CAPITAL_EXPENDITURES = "CAPITAL_EXPENDITURES"
    FREE_CASH_FLOW = "FREE_CASH_FLOW"

    # ------------------------------------------------------------------
    # Generic buckets / other
    # ------------------------------------------------------------------
    OTHER_OPERATING_INCOME_EXPENSE = "OTHER_OPERATING_INCOME_EXPENSE"
    OTHER_ASSETS = "OTHER_ASSETS"
    OTHER_LIABILITIES = "OTHER_LIABILITIES"
    OTHER_EQUITY = "OTHER_EQUITY"
    OTHER_CASH_FLOW_FROM_OPERATIONS = "OTHER_CASH_FLOW_FROM_OPERATIONS"
    OTHER_CASH_FLOW_FROM_INVESTING = "OTHER_CASH_FLOW_FROM_INVESTING"
    OTHER_CASH_FLOW_FROM_FINANCING = "OTHER_CASH_FLOW_FROM_FINANCING"


__all__ = ["CanonicalStatementMetric"]
