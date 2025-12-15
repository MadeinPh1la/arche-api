# src/arche_api/domain/enums/derived_metric.py
# Copyright (c) Arche.
# SPDX-License-Identifier: MIT
"""Derived financial metrics enumeration.

Purpose:
    Define a stable, provider-agnostic set of derived financial metrics
    computed on top of canonical statement payloads. These metrics represent
    common institutional analytics such as margins, growth rates, cash flow
    measures, capital structure ratios, and returns.

Layer:
    domain

Notes:
    - Values are string identifiers suitable for JSON and external contracts.
    - This enum is intentionally separate from CanonicalStatementMetric to
      distinguish between "raw" statement values and derived analytics.
    - Metrics in this enum are computed by the derived-metrics engine in
      :mod:`arche_api.domain.services.derived_metrics_engine`.
"""

from __future__ import annotations

from enum import Enum


class DerivedMetric(str, Enum):
    """Derived financial metrics used in analytics and modeling."""

    # ------------------------------------------------------------------ #
    # Margins                                                            #
    # ------------------------------------------------------------------ #
    GROSS_MARGIN = "GROSS_MARGIN"
    OPERATING_MARGIN = "OPERATING_MARGIN"
    NET_MARGIN = "NET_MARGIN"

    # ------------------------------------------------------------------ #
    # Revenue and EPS growth                                             #
    # ------------------------------------------------------------------ #
    REVENUE_GROWTH_YOY = "REVENUE_GROWTH_YOY"
    REVENUE_GROWTH_QOQ = "REVENUE_GROWTH_QOQ"
    REVENUE_GROWTH_TTM = "REVENUE_GROWTH_TTM"
    EPS_DILUTED_GROWTH = "EPS_DILUTED_GROWTH"

    # ------------------------------------------------------------------ #
    # Earnings and cash-flow levels                                      #
    # ------------------------------------------------------------------ #
    EBITDA = "EBITDA"
    EBIT = "EBIT"
    LEVERED_FREE_CASH_FLOW = "LEVERED_FREE_CASH_FLOW"
    UNLEVERED_FREE_CASH_FLOW = "UNLEVERED_FREE_CASH_FLOW"

    # ------------------------------------------------------------------ #
    # Liquidity / capital structure                                      #
    # ------------------------------------------------------------------ #
    WORKING_CAPITAL = "WORKING_CAPITAL"
    DEBT_TO_EQUITY = "DEBT_TO_EQUITY"
    INTEREST_COVERAGE = "INTEREST_COVERAGE"

    # ------------------------------------------------------------------ #
    # Returns                                                            #
    # ------------------------------------------------------------------ #
    ROE = "ROE"
    ROA = "ROA"
    ROIC = "ROIC"


__all__ = ["DerivedMetric"]
