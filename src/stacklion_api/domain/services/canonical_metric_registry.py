# src/stacklion_api/domain/services/canonical_metric_registry.py
# Copyright (c) Stacklion.
# SPDX-License-Identifier: MIT
"""Canonical metric registry for Tier-1 statement metrics.

Purpose:
    Provide metadata for :class:`CanonicalStatementMetric` values used in
    normalized statement payloads and fundamentals surfaces. The registry
    defines:
        * Human-readable labels.
        * High-level categories (e.g., revenue, assets, cash_flow).
        * Statement-type affinity (IS / BS / CF).
        * Flags for primary vs. non-primary and derived vs. raw metrics.

Layer:
    domain

Notes:
    - This module is pure domain logic:
        * No logging.
        * No HTTP or transport concerns.
        * No persistence or gateways.
    - The registry is strictly additive and backward compatible. Existing
      enum values and semantics must not change.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Final

from stacklion_api.domain.enums.canonical_statement_metric import CanonicalStatementMetric
from stacklion_api.domain.enums.edgar import StatementType

# --------------------------------------------------------------------------- #
# Types and constants                                                         #
# --------------------------------------------------------------------------- #


_ALLOWED_STATEMENT_TYPES: Final[set[str]] = {"IS", "BS", "CF"}

_ALLOWED_CATEGORIES: Final[set[str]] = {
    "REVENUE",
    "EXPENSE",
    "PROFITABILITY",
    "ASSETS",
    "LIABILITIES",
    "EQUITY",
    "CASH_FLOW",
    "CAPITAL_STRUCTURE",
    "PER_SHARE",
    "SHARES",
    "OTHER",
}

# Map application-level StatementType → registry statement_type code
_STATEMENT_TYPE_TO_REGISTRY_CODE: Final[dict[StatementType, str]] = {
    StatementType.INCOME_STATEMENT: "IS",
    StatementType.BALANCE_SHEET: "BS",
    StatementType.CASH_FLOW_STATEMENT: "CF",
}


@dataclass(frozen=True)
class CanonicalMetricMetadata:
    """Metadata describing a canonical financial statement metric.

    Attributes:
        metric:
            Canonical metric enum member.
        label:
            Human-readable label suitable for UIs and API documentation.
        category:
            High-level modeling category (e.g., "REVENUE", "ASSETS").
            Must be one of :data:`_ALLOWED_CATEGORIES`.
        statement_type:
            Primary statement affinity for the metric:
                * ``"IS"`` for income statement.
                * ``"BS"`` for balance sheet.
                * ``"CF"`` for cash flow statement.
        is_primary:
            Whether this metric is part of the Tier-1 "primary" surface
            for fundamentals/time-series APIs.
        is_derived:
            Whether this metric is derived from other metrics rather than
            directly sourced from filings.
    """

    metric: CanonicalStatementMetric
    label: str
    category: str
    statement_type: str
    is_primary: bool
    is_derived: bool = False


# --------------------------------------------------------------------------- #
# Registry                                                                    #
# --------------------------------------------------------------------------- #


_CANONICAL_METRIC_REGISTRY: dict[CanonicalStatementMetric, CanonicalMetricMetadata] = {
    # ------------------------------------------------------------------ #
    # Income Statement (Performance)                                     #
    # ------------------------------------------------------------------ #
    CanonicalStatementMetric.REVENUE: CanonicalMetricMetadata(
        metric=CanonicalStatementMetric.REVENUE,
        label="Revenue",
        category="REVENUE",
        statement_type="IS",
        is_primary=True,
    ),
    CanonicalStatementMetric.COST_OF_REVENUE: CanonicalMetricMetadata(
        metric=CanonicalStatementMetric.COST_OF_REVENUE,
        label="Cost of revenue",
        category="EXPENSE",
        statement_type="IS",
        is_primary=False,
    ),
    CanonicalStatementMetric.GROSS_PROFIT: CanonicalMetricMetadata(
        metric=CanonicalStatementMetric.GROSS_PROFIT,
        label="Gross profit",
        category="PROFITABILITY",
        statement_type="IS",
        is_primary=True,
    ),
    CanonicalStatementMetric.RESEARCH_AND_DEVELOPMENT_EXPENSE: CanonicalMetricMetadata(
        metric=CanonicalStatementMetric.RESEARCH_AND_DEVELOPMENT_EXPENSE,
        label="Research and development expense",
        category="EXPENSE",
        statement_type="IS",
        is_primary=False,
    ),
    CanonicalStatementMetric.SELLING_GENERAL_AND_ADMINISTRATIVE_EXPENSE: CanonicalMetricMetadata(
        metric=CanonicalStatementMetric.SELLING_GENERAL_AND_ADMINISTRATIVE_EXPENSE,
        label="Selling, general and administrative expense",
        category="EXPENSE",
        statement_type="IS",
        is_primary=False,
    ),
    CanonicalStatementMetric.DEPRECIATION_AND_AMORTIZATION_EXPENSE: CanonicalMetricMetadata(
        metric=CanonicalStatementMetric.DEPRECIATION_AND_AMORTIZATION_EXPENSE,
        label="Depreciation and amortization",
        category="EXPENSE",
        statement_type="IS",
        is_primary=False,
        is_derived=False,
    ),
    CanonicalStatementMetric.OPERATING_INCOME: CanonicalMetricMetadata(
        metric=CanonicalStatementMetric.OPERATING_INCOME,
        label="Operating income",
        category="PROFITABILITY",
        statement_type="IS",
        is_primary=True,
        is_derived=True,
    ),
    CanonicalStatementMetric.OPERATING_EXPENSE: CanonicalMetricMetadata(
        metric=CanonicalStatementMetric.OPERATING_EXPENSE,
        label="Operating expense",
        category="EXPENSE",
        statement_type="IS",
        is_primary=False,
        is_derived=True,
    ),
    CanonicalStatementMetric.INTEREST_INCOME: CanonicalMetricMetadata(
        metric=CanonicalStatementMetric.INTEREST_INCOME,
        label="Interest income",
        category="OTHER",
        statement_type="IS",
        is_primary=False,
    ),
    CanonicalStatementMetric.INTEREST_EXPENSE: CanonicalMetricMetadata(
        metric=CanonicalStatementMetric.INTEREST_EXPENSE,
        label="Interest expense",
        category="EXPENSE",
        statement_type="IS",
        is_primary=False,
    ),
    CanonicalStatementMetric.OTHER_NON_OPERATING_INCOME_EXPENSE: CanonicalMetricMetadata(
        metric=CanonicalStatementMetric.OTHER_NON_OPERATING_INCOME_EXPENSE,
        label="Other non-operating income (expense)",
        category="OTHER",
        statement_type="IS",
        is_primary=False,
    ),
    CanonicalStatementMetric.INCOME_BEFORE_TAX: CanonicalMetricMetadata(
        metric=CanonicalStatementMetric.INCOME_BEFORE_TAX,
        label="Income before tax",
        category="PROFITABILITY",
        statement_type="IS",
        is_primary=False,
        is_derived=True,
    ),
    CanonicalStatementMetric.INCOME_TAX_EXPENSE: CanonicalMetricMetadata(
        metric=CanonicalStatementMetric.INCOME_TAX_EXPENSE,
        label="Income tax expense",
        category="EXPENSE",
        statement_type="IS",
        is_primary=False,
    ),
    CanonicalStatementMetric.NET_INCOME: CanonicalMetricMetadata(
        metric=CanonicalStatementMetric.NET_INCOME,
        label="Net income",
        category="PROFITABILITY",
        statement_type="IS",
        is_primary=True,
        is_derived=True,
    ),
    CanonicalStatementMetric.BASIC_EPS: CanonicalMetricMetadata(
        metric=CanonicalStatementMetric.BASIC_EPS,
        label="Basic earnings per share",
        category="PER_SHARE",
        statement_type="IS",
        is_primary=True,
        is_derived=True,
    ),
    CanonicalStatementMetric.DILUTED_EPS: CanonicalMetricMetadata(
        metric=CanonicalStatementMetric.DILUTED_EPS,
        label="Diluted earnings per share",
        category="PER_SHARE",
        statement_type="IS",
        is_primary=True,
        is_derived=True,
    ),
    CanonicalStatementMetric.WEIGHTED_AVERAGE_SHARES_BASIC: CanonicalMetricMetadata(
        metric=CanonicalStatementMetric.WEIGHTED_AVERAGE_SHARES_BASIC,
        label="Weighted average shares (basic)",
        category="SHARES",
        statement_type="IS",
        is_primary=False,
    ),
    CanonicalStatementMetric.WEIGHTED_AVERAGE_SHARES_DILUTED: CanonicalMetricMetadata(
        metric=CanonicalStatementMetric.WEIGHTED_AVERAGE_SHARES_DILUTED,
        label="Weighted average shares (diluted)",
        category="SHARES",
        statement_type="IS",
        is_primary=False,
    ),
    # ------------------------------------------------------------------ #
    # Balance Sheet (Position)                                           #
    # ------------------------------------------------------------------ #
    CanonicalStatementMetric.TOTAL_ASSETS: CanonicalMetricMetadata(
        metric=CanonicalStatementMetric.TOTAL_ASSETS,
        label="Total assets",
        category="ASSETS",
        statement_type="BS",
        is_primary=True,
    ),
    CanonicalStatementMetric.TOTAL_CURRENT_ASSETS: CanonicalMetricMetadata(
        metric=CanonicalStatementMetric.TOTAL_CURRENT_ASSETS,
        label="Total current assets",
        category="ASSETS",
        statement_type="BS",
        is_primary=False,
        is_derived=True,
    ),
    CanonicalStatementMetric.CASH_AND_CASH_EQUIVALENTS: CanonicalMetricMetadata(
        metric=CanonicalStatementMetric.CASH_AND_CASH_EQUIVALENTS,
        label="Cash and cash equivalents",
        category="ASSETS",
        statement_type="BS",
        is_primary=True,
    ),
    CanonicalStatementMetric.SHORT_TERM_INVESTMENTS: CanonicalMetricMetadata(
        metric=CanonicalStatementMetric.SHORT_TERM_INVESTMENTS,
        label="Short-term investments",
        category="ASSETS",
        statement_type="BS",
        is_primary=False,
    ),
    CanonicalStatementMetric.ACCOUNTS_RECEIVABLE_NET: CanonicalMetricMetadata(
        metric=CanonicalStatementMetric.ACCOUNTS_RECEIVABLE_NET,
        label="Accounts receivable, net",
        category="ASSETS",
        statement_type="BS",
        is_primary=False,
    ),
    CanonicalStatementMetric.INVENTORIES: CanonicalMetricMetadata(
        metric=CanonicalStatementMetric.INVENTORIES,
        label="Inventories",
        category="ASSETS",
        statement_type="BS",
        is_primary=False,
    ),
    CanonicalStatementMetric.OTHER_CURRENT_ASSETS: CanonicalMetricMetadata(
        metric=CanonicalStatementMetric.OTHER_CURRENT_ASSETS,
        label="Other current assets",
        category="ASSETS",
        statement_type="BS",
        is_primary=False,
    ),
    CanonicalStatementMetric.TOTAL_NON_CURRENT_ASSETS: CanonicalMetricMetadata(
        metric=CanonicalStatementMetric.TOTAL_NON_CURRENT_ASSETS,
        label="Total non-current assets",
        category="ASSETS",
        statement_type="BS",
        is_primary=False,
        is_derived=True,
    ),
    CanonicalStatementMetric.PROPERTY_PLANT_AND_EQUIPMENT_NET: CanonicalMetricMetadata(
        metric=CanonicalStatementMetric.PROPERTY_PLANT_AND_EQUIPMENT_NET,
        label="Property, plant and equipment, net",
        category="ASSETS",
        statement_type="BS",
        is_primary=False,
    ),
    CanonicalStatementMetric.GOODWILL: CanonicalMetricMetadata(
        metric=CanonicalStatementMetric.GOODWILL,
        label="Goodwill",
        category="ASSETS",
        statement_type="BS",
        is_primary=False,
    ),
    CanonicalStatementMetric.INTANGIBLE_ASSETS_NET: CanonicalMetricMetadata(
        metric=CanonicalStatementMetric.INTANGIBLE_ASSETS_NET,
        label="Intangible assets, net",
        category="ASSETS",
        statement_type="BS",
        is_primary=False,
    ),
    CanonicalStatementMetric.OTHER_NON_CURRENT_ASSETS: CanonicalMetricMetadata(
        metric=CanonicalStatementMetric.OTHER_NON_CURRENT_ASSETS,
        label="Other non-current assets",
        category="ASSETS",
        statement_type="BS",
        is_primary=False,
    ),
    CanonicalStatementMetric.TOTAL_LIABILITIES: CanonicalMetricMetadata(
        metric=CanonicalStatementMetric.TOTAL_LIABILITIES,
        label="Total liabilities",
        category="LIABILITIES",
        statement_type="BS",
        is_primary=True,
    ),
    CanonicalStatementMetric.TOTAL_CURRENT_LIABILITIES: CanonicalMetricMetadata(
        metric=CanonicalStatementMetric.TOTAL_CURRENT_LIABILITIES,
        label="Total current liabilities",
        category="LIABILITIES",
        statement_type="BS",
        is_primary=False,
        is_derived=True,
    ),
    CanonicalStatementMetric.ACCOUNTS_PAYABLE: CanonicalMetricMetadata(
        metric=CanonicalStatementMetric.ACCOUNTS_PAYABLE,
        label="Accounts payable",
        category="LIABILITIES",
        statement_type="BS",
        is_primary=False,
    ),
    CanonicalStatementMetric.SHORT_TERM_DEBT: CanonicalMetricMetadata(
        metric=CanonicalStatementMetric.SHORT_TERM_DEBT,
        label="Short-term debt",
        category="CAPITAL_STRUCTURE",
        statement_type="BS",
        is_primary=False,
    ),
    CanonicalStatementMetric.CURRENT_PORTION_OF_LONG_TERM_DEBT: CanonicalMetricMetadata(
        metric=CanonicalStatementMetric.CURRENT_PORTION_OF_LONG_TERM_DEBT,
        label="Current portion of long-term debt",
        category="CAPITAL_STRUCTURE",
        statement_type="BS",
        is_primary=False,
    ),
    CanonicalStatementMetric.OTHER_CURRENT_LIABILITIES: CanonicalMetricMetadata(
        metric=CanonicalStatementMetric.OTHER_CURRENT_LIABILITIES,
        label="Other current liabilities",
        category="LIABILITIES",
        statement_type="BS",
        is_primary=False,
    ),
    CanonicalStatementMetric.TOTAL_NON_CURRENT_LIABILITIES: CanonicalMetricMetadata(
        metric=CanonicalStatementMetric.TOTAL_NON_CURRENT_LIABILITIES,
        label="Total non-current liabilities",
        category="LIABILITIES",
        statement_type="BS",
        is_primary=False,
        is_derived=True,
    ),
    CanonicalStatementMetric.LONG_TERM_DEBT: CanonicalMetricMetadata(
        metric=CanonicalStatementMetric.LONG_TERM_DEBT,
        label="Long-term debt",
        category="CAPITAL_STRUCTURE",
        statement_type="BS",
        is_primary=True,
    ),
    CanonicalStatementMetric.OTHER_NON_CURRENT_LIABILITIES: CanonicalMetricMetadata(
        metric=CanonicalStatementMetric.OTHER_NON_CURRENT_LIABILITIES,
        label="Other non-current liabilities",
        category="LIABILITIES",
        statement_type="BS",
        is_primary=False,
    ),
    CanonicalStatementMetric.TOTAL_EQUITY: CanonicalMetricMetadata(
        metric=CanonicalStatementMetric.TOTAL_EQUITY,
        label="Total equity",
        category="EQUITY",
        statement_type="BS",
        is_primary=True,
        is_derived=True,
    ),
    CanonicalStatementMetric.RETAINED_EARNINGS: CanonicalMetricMetadata(
        metric=CanonicalStatementMetric.RETAINED_EARNINGS,
        label="Retained earnings",
        category="EQUITY",
        statement_type="BS",
        is_primary=False,
    ),
    CanonicalStatementMetric.ADDITIONAL_PAID_IN_CAPITAL: CanonicalMetricMetadata(
        metric=CanonicalStatementMetric.ADDITIONAL_PAID_IN_CAPITAL,
        label="Additional paid-in capital",
        category="EQUITY",
        statement_type="BS",
        is_primary=False,
    ),
    CanonicalStatementMetric.TREASURY_STOCK: CanonicalMetricMetadata(
        metric=CanonicalStatementMetric.TREASURY_STOCK,
        label="Treasury stock",
        category="EQUITY",
        statement_type="BS",
        is_primary=False,
    ),
    CanonicalStatementMetric.ACCUMULATED_OTHER_COMPREHENSIVE_INCOME: CanonicalMetricMetadata(
        metric=CanonicalStatementMetric.ACCUMULATED_OTHER_COMPREHENSIVE_INCOME,
        label="Accumulated other comprehensive income",
        category="EQUITY",
        statement_type="BS",
        is_primary=False,
    ),
    # ------------------------------------------------------------------ #
    # Cash Flow Statement (Flows)                                        #
    # ------------------------------------------------------------------ #
    CanonicalStatementMetric.NET_CASH_FROM_OPERATING_ACTIVITIES: CanonicalMetricMetadata(
        metric=CanonicalStatementMetric.NET_CASH_FROM_OPERATING_ACTIVITIES,
        label="Net cash from operating activities",
        category="CASH_FLOW",
        statement_type="CF",
        is_primary=True,
    ),
    CanonicalStatementMetric.NET_CASH_FROM_INVESTING_ACTIVITIES: CanonicalMetricMetadata(
        metric=CanonicalStatementMetric.NET_CASH_FROM_INVESTING_ACTIVITIES,
        label="Net cash from investing activities",
        category="CASH_FLOW",
        statement_type="CF",
        is_primary=False,
    ),
    CanonicalStatementMetric.NET_CASH_FROM_FINANCING_ACTIVITIES: CanonicalMetricMetadata(
        metric=CanonicalStatementMetric.NET_CASH_FROM_FINANCING_ACTIVITIES,
        label="Net cash from financing activities",
        category="CASH_FLOW",
        statement_type="CF",
        is_primary=False,
    ),
    CanonicalStatementMetric.NET_INCREASE_DECREASE_IN_CASH: CanonicalMetricMetadata(
        metric=CanonicalStatementMetric.NET_INCREASE_DECREASE_IN_CASH,
        label="Net change in cash",
        category="CASH_FLOW",
        statement_type="CF",
        is_primary=True,
        is_derived=True,
    ),
    CanonicalStatementMetric.CASH_PAID_FOR_INTEREST: CanonicalMetricMetadata(
        metric=CanonicalStatementMetric.CASH_PAID_FOR_INTEREST,
        label="Cash paid for interest",
        category="CASH_FLOW",
        statement_type="CF",
        is_primary=False,
    ),
    CanonicalStatementMetric.CASH_PAID_FOR_INCOME_TAXES: CanonicalMetricMetadata(
        metric=CanonicalStatementMetric.CASH_PAID_FOR_INCOME_TAXES,
        label="Cash paid for income taxes",
        category="CASH_FLOW",
        statement_type="CF",
        is_primary=False,
    ),
    CanonicalStatementMetric.CAPITAL_EXPENDITURES: CanonicalMetricMetadata(
        metric=CanonicalStatementMetric.CAPITAL_EXPENDITURES,
        label="Capital expenditures",
        category="CASH_FLOW",
        statement_type="CF",
        is_primary=True,
    ),
    CanonicalStatementMetric.FREE_CASH_FLOW: CanonicalMetricMetadata(
        metric=CanonicalStatementMetric.FREE_CASH_FLOW,
        label="Free cash flow",
        category="CASH_FLOW",
        statement_type="CF",
        is_primary=True,
        is_derived=True,
    ),
    # ------------------------------------------------------------------ #
    # Generic buckets / other                                            #
    # ------------------------------------------------------------------ #
    CanonicalStatementMetric.OTHER_OPERATING_INCOME_EXPENSE: CanonicalMetricMetadata(
        metric=CanonicalStatementMetric.OTHER_OPERATING_INCOME_EXPENSE,
        label="Other operating income (expense)",
        category="OTHER",
        statement_type="IS",
        is_primary=False,
    ),
    CanonicalStatementMetric.OTHER_ASSETS: CanonicalMetricMetadata(
        metric=CanonicalStatementMetric.OTHER_ASSETS,
        label="Other assets",
        category="ASSETS",
        statement_type="BS",
        is_primary=False,
    ),
    CanonicalStatementMetric.OTHER_LIABILITIES: CanonicalMetricMetadata(
        metric=CanonicalStatementMetric.OTHER_LIABILITIES,
        label="Other liabilities",
        category="LIABILITIES",
        statement_type="BS",
        is_primary=False,
    ),
    CanonicalStatementMetric.OTHER_EQUITY: CanonicalMetricMetadata(
        metric=CanonicalStatementMetric.OTHER_EQUITY,
        label="Other equity",
        category="EQUITY",
        statement_type="BS",
        is_primary=False,
    ),
    CanonicalStatementMetric.OTHER_CASH_FLOW_FROM_OPERATIONS: CanonicalMetricMetadata(
        metric=CanonicalStatementMetric.OTHER_CASH_FLOW_FROM_OPERATIONS,
        label="Other operating cash flows",
        category="CASH_FLOW",
        statement_type="CF",
        is_primary=False,
    ),
    CanonicalStatementMetric.OTHER_CASH_FLOW_FROM_INVESTING: CanonicalMetricMetadata(
        metric=CanonicalStatementMetric.OTHER_CASH_FLOW_FROM_INVESTING,
        label="Other investing cash flows",
        category="CASH_FLOW",
        statement_type="CF",
        is_primary=False,
    ),
    CanonicalStatementMetric.OTHER_CASH_FLOW_FROM_FINANCING: CanonicalMetricMetadata(
        metric=CanonicalStatementMetric.OTHER_CASH_FLOW_FROM_FINANCING,
        label="Other financing cash flows",
        category="CASH_FLOW",
        statement_type="CF",
        is_primary=False,
    ),
}


# Tier-1 pinned set: "Bloomberg-class" core metrics that must never disappear
# without an intentional test update.
TIER1_METRICS_PINNED: Final[tuple[CanonicalStatementMetric, ...]] = (
    CanonicalStatementMetric.REVENUE,
    CanonicalStatementMetric.GROSS_PROFIT,
    CanonicalStatementMetric.OPERATING_INCOME,
    CanonicalStatementMetric.NET_INCOME,
    CanonicalStatementMetric.BASIC_EPS,
    CanonicalStatementMetric.DILUTED_EPS,
    CanonicalStatementMetric.TOTAL_ASSETS,
    CanonicalStatementMetric.TOTAL_LIABILITIES,
    CanonicalStatementMetric.TOTAL_EQUITY,
    CanonicalStatementMetric.CASH_AND_CASH_EQUIVALENTS,
    CanonicalStatementMetric.LONG_TERM_DEBT,
    CanonicalStatementMetric.NET_CASH_FROM_OPERATING_ACTIVITIES,
    CanonicalStatementMetric.CAPITAL_EXPENDITURES,
    CanonicalStatementMetric.FREE_CASH_FLOW,
    CanonicalStatementMetric.NET_INCREASE_DECREASE_IN_CASH,
)


# --------------------------------------------------------------------------- #
# Public API                                                                  #
# --------------------------------------------------------------------------- #


def get_metric_metadata(metric: CanonicalStatementMetric) -> CanonicalMetricMetadata:
    """Return metadata for a canonical metric.

    Args:
        metric:
            Canonical metric enum value.

    Returns:
        Metadata for the given metric.

    Raises:
        KeyError:
            If the metric is not present in the registry.
    """
    return _CANONICAL_METRIC_REGISTRY[metric]


def iter_metric_metadata() -> tuple[CanonicalMetricMetadata, ...]:
    """Return all metric metadata entries in deterministic order.

    Returns:
        Tuple of metric metadata entries sorted by metric name.
    """
    return tuple(
        sorted(
            _CANONICAL_METRIC_REGISTRY.values(),
            key=lambda m: m.metric.value,
        )
    )


def get_tier1_metrics() -> tuple[CanonicalStatementMetric, ...]:
    """Return the Tier-1 canonical metrics.

    Returns:
        Tuple of Tier-1 metric enum values.
    """
    return TIER1_METRICS_PINNED


def get_tier1_metrics_for_statement_type(
    statement_type: StatementType,
) -> tuple[CanonicalStatementMetric, ...]:
    """Return Tier-1 canonical metrics for a given statement type.

    This helper restricts the pinned Tier-1 set to metrics whose primary
    statement affinity matches the requested statement type.

    Args:
        statement_type:
            High-level statement type used by fundamentals/time-series
            surfaces (e.g., INCOME_STATEMENT, BALANCE_SHEET).

    Returns:
        Tuple of Tier-1 canonical metrics associated with the statement type.
        Returns an empty tuple when no Tier-1 metrics are registered for the
        given statement type.
    """
    registry_code = _STATEMENT_TYPE_TO_REGISTRY_CODE.get(statement_type)
    if registry_code is None:
        return ()

    return tuple(
        meta.metric
        for meta in _CANONICAL_METRIC_REGISTRY.values()
        if meta.metric in TIER1_METRICS_PINNED and meta.statement_type == registry_code
    )


__all__ = [
    "CanonicalMetricMetadata",
    "TIER1_METRICS_PINNED",
    "get_metric_metadata",
    "iter_metric_metadata",
    "get_tier1_metrics",
    "get_tier1_metrics_for_statement_type",
]
