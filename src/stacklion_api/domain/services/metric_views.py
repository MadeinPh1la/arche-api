# src/stacklion_api/domain/services/metric_views.py
# Copyright (c)
# SPDX-License-Identifier: MIT
"""Domain registry for derived-metric bundles ("views").

Purpose:
    Define curated, opinionated bundles of :class:`DerivedMetric` values that
    represent common modeling "views" (e.g., core fundamentals). These bundles
    are consumed by application-layer use-cases via the EDGAR controller.

Layer:
    domain

Notes:
    - This module is pure domain logic:
        * No logging.
        * No HTTP or transport concerns.
        * No persistence or gateways.
    - Codes are case-insensitive at lookup time but stored canonically in
      lower_snake_case form (e.g., "core_fundamentals").
"""

from __future__ import annotations

from dataclasses import dataclass

from stacklion_api.domain.enums.derived_metric import DerivedMetric


@dataclass(frozen=True)
class MetricView:
    """Definition of a metric bundle ("view") used for modeling.

    Attributes:
        code:
            Stable identifier for the view, used in APIs and configuration.
            Codes are normalized to lower_snake_case (e.g., "core_fundamentals").
        label:
            Short human-readable label suitable for UIs.
        description:
            Longer description of the view's intent and typical use-cases.
        metrics:
            Tuple of derived metrics that belong to this view. Ordering is
            stable and preserved when the view is expanded to a metrics list.
    """

    code: str
    label: str
    description: str
    metrics: tuple[DerivedMetric, ...]


# --------------------------------------------------------------------------- #
# Registry                                                                    #
# --------------------------------------------------------------------------- #


def _normalize_code(raw: str) -> str:
    """Normalize a view code for registry lookups.

    Args:
        raw:
            Raw view code from user input or configuration.

    Returns:
        Normalized lower-case code with surrounding whitespace stripped.
    """
    return raw.strip().lower()


# Core "Bloomberg-class" fundamentals view. The goal is to provide a
# practical default for modeling workflows without forcing callers to
# enumerate individual metrics.
_CORE_FUNDAMENTALS = MetricView(
    code="core_fundamentals",
    label="Core fundamentals",
    description=(
        "Core fundamentals bundle including margins, revenue growth, cash "
        "flows, capital structure, and basic returns suitable for "
        "institutional modeling use-cases."
    ),
    metrics=(
        # Margins
        DerivedMetric.GROSS_MARGIN,
        DerivedMetric.OPERATING_MARGIN,
        DerivedMetric.NET_MARGIN,
        # Growth
        DerivedMetric.REVENUE_GROWTH_YOY,
        DerivedMetric.REVENUE_GROWTH_QOQ,
        DerivedMetric.REVENUE_GROWTH_TTM,
        DerivedMetric.EPS_DILUTED_GROWTH,
        # Cash-flow levels
        DerivedMetric.EBITDA,
        DerivedMetric.EBIT,
        DerivedMetric.LEVERED_FREE_CASH_FLOW,
        DerivedMetric.UNLEVERED_FREE_CASH_FLOW,
        # Liquidity / capital structure
        DerivedMetric.WORKING_CAPITAL,
        DerivedMetric.DEBT_TO_EQUITY,
        DerivedMetric.INTEREST_COVERAGE,
        # Returns
        DerivedMetric.ROE,
        DerivedMetric.ROA,
        DerivedMetric.ROIC,
    ),
)

_METRIC_VIEWS_BY_CODE: dict[str, MetricView] = {
    _normalize_code(_CORE_FUNDAMENTALS.code): _CORE_FUNDAMENTALS,
}


def get_metric_view(code: str) -> MetricView | None:
    """Return the metric view for a given code, if registered.

    Args:
        code:
            View identifier (case-insensitive).

    Returns:
        The matching :class:`MetricView` if found, otherwise ``None``.
    """
    if not code:
        return None
    return _METRIC_VIEWS_BY_CODE.get(_normalize_code(code))


def list_metric_views() -> list[MetricView]:
    """Return all registered metric views in deterministic order.

    Returns:
        List of metric views sorted by their canonical code.
    """
    return sorted(_METRIC_VIEWS_BY_CODE.values(), key=lambda v: v.code)


def expand_view_metrics(code: str) -> tuple[DerivedMetric, ...]:
    """Resolve a view code into its ordered metrics tuple.

    Args:
        code:
            View identifier to expand.

    Returns:
        Tuple of derived metric identifiers associated with the view.

    Raises:
        ValueError:
            If ``code`` does not correspond to a registered view.
    """
    view = get_metric_view(code)
    if view is None:
        raise ValueError(f"Unknown metric view: {code}")
    return view.metrics


__all__ = ["MetricView", "get_metric_view", "list_metric_views", "expand_view_metrics"]
