# src/arche_api/domain/services/reconciliation_rule_sets.py
# Copyright (c)
# SPDX-License-Identifier: MIT
"""Reconciliation rule sets for the EDGAR domain.

Purpose:
    Define curated reconciliation rule sets used by the reconciliation
    engine. These rule sets provide a stable, versioned configuration
    for accounting identity, calendar, and other reconciliation checks.

Layer:
    domain/services

Notes:
    - Pure domain module:
        * No logging.
        * No HTTP or transport concerns.
        * No persistence or gateways.
    - Rule sets are intentionally small and conservative in E11-A. More
      rules can be added in later phases in a strictly additive fashion.
"""

from __future__ import annotations

from decimal import Decimal
from typing import Final

from arche_api.domain.entities.edgar_reconciliation import (
    CalendarReconciliationRule,
    IdentityReconciliationRule,
    ReconciliationRule,
)
from arche_api.domain.enums.canonical_statement_metric import CanonicalStatementMetric
from arche_api.domain.enums.edgar import MaterialityClass, StatementType
from arche_api.domain.enums.edgar_reconciliation import ReconciliationRuleCategory

DEFAULT_E11_RULE_SET_ID: Final[str] = "E11_RULESET_V1"


def get_default_e11_rules() -> tuple[ReconciliationRule, ...]:
    """Return the default E11 reconciliation rule set.

    The default rule set focuses on high-signal, low-regret checks:

        * Cash-flow identity:
            Net change in cash equals operating + investing + financing
            cash flows.

        * Balance-sheet identity:
            Total assets equals total liabilities plus total equity.

        * Calendar behavior:
            Fiscal year-end month must be in the allowed set (default:
            December), with no opinion on 53-week years at this stage.

    Returns:
        Tuple of reconciliation rule specifications.
    """
    rules: list[ReconciliationRule] = []

    # ------------------------------------------------------------------ #
    # Identity: net change in cash equals sum of cash flows              #
    # ------------------------------------------------------------------ #

    rules.append(
        IdentityReconciliationRule(
            rule_id="E11_IDENTITY_NET_CHANGE_CASH",
            name="Net change in cash equals operating + investing + financing cash flows",
            category=ReconciliationRuleCategory.IDENTITY,
            severity=MaterialityClass.MEDIUM,
            lhs_metrics=(CanonicalStatementMetric.NET_INCREASE_DECREASE_IN_CASH,),
            rhs_metrics=(
                CanonicalStatementMetric.NET_CASH_FROM_OPERATING_ACTIVITIES,
                CanonicalStatementMetric.NET_CASH_FROM_INVESTING_ACTIVITIES,
                CanonicalStatementMetric.NET_CASH_FROM_FINANCING_ACTIVITIES,
            ),
            tolerance=Decimal("0.01"),
            applicable_statement_types=(StatementType.CASH_FLOW_STATEMENT,),
            description=(
                "Validate that net change in cash equals the sum of net cash from "
                "operating, investing, and financing activities."
            ),
        )
    )

    # ------------------------------------------------------------------ #
    # Identity: balance sheet equality                                   #
    # ------------------------------------------------------------------ #

    rules.append(
        IdentityReconciliationRule(
            rule_id="E11_IDENTITY_BALANCE_SHEET",
            name="Assets equal liabilities plus equity",
            category=ReconciliationRuleCategory.IDENTITY,
            severity=MaterialityClass.HIGH,
            lhs_metrics=(CanonicalStatementMetric.TOTAL_ASSETS,),
            rhs_metrics=(
                CanonicalStatementMetric.TOTAL_LIABILITIES,
                CanonicalStatementMetric.TOTAL_EQUITY,
            ),
            tolerance=Decimal("0.01"),
            applicable_statement_types=(StatementType.BALANCE_SHEET,),
            description="Validate that total assets equal total liabilities plus total equity.",
        )
    )

    # ------------------------------------------------------------------ #
    # Calendar: fiscal year-end month constraint                         #
    # ------------------------------------------------------------------ #

    rules.append(
        CalendarReconciliationRule(
            rule_id="E11_CALENDAR_FYE_MONTH",
            name="Fiscal year-end month is in allowed set",
            category=ReconciliationRuleCategory.CALENDAR,
            severity=MaterialityClass.LOW,
            allowed_fye_months=(12,),
            allow_53_week=True,
            max_gap_days=730,
            description=(
                "Ensure that fiscal year-end dates fall in the allowed set of "
                "months (default: December), while permitting 53-week years."
            ),
        )
    )

    return tuple(rules)


__all__ = ["DEFAULT_E11_RULE_SET_ID", "get_default_e11_rules"]
