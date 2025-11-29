# src/stacklion_api/domain/enums/derived_metric_category.py
# Copyright (c) Stacklion.
# SPDX-License-Identifier: MIT
"""Derived metric category enumeration.

Purpose:
    Provide high-level, stable categories for derived financial metrics such
    as margins, growth, cash-flow measures, leverage, and returns. These
    categories are used for documentation, grouping, and opinionated metric
    bundles in modeling and analytics workflows.

Layer:
    domain

Notes:
    - Values are string identifiers suitable for JSON and external contracts.
    - Categories are intentionally coarse-grained to remain stable over time.
"""

from __future__ import annotations

from enum import Enum


class DerivedMetricCategory(str, Enum):
    """High-level categories for derived financial metrics."""

    MARGIN = "MARGIN"
    GROWTH = "GROWTH"
    CASH_FLOW = "CASH_FLOW"
    LEVERAGE = "LEVERAGE"
    RETURN = "RETURN"


__all__ = ["DerivedMetricCategory"]
