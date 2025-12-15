# src/arche_api/domain/enums/edgar_reconciliation.py
# Copyright (c)
# SPDX-License-Identifier: MIT
"""Reconciliation-specific enums for EDGAR domain.

Purpose:
    Define enums used by the reconciliation domain kernel, including
    rule categories and evaluation statuses.

Layer:
    domain/enums

Notes:
    - Pure domain types:
        * No logging.
        * No HTTP or transport concerns.
        * No persistence or gateways.
"""

from __future__ import annotations

from enum import Enum

from arche_api.domain.enums.edgar import MaterialityClass


class ReconciliationRuleCategory(str, Enum):
    """High-level reconciliation rule categories."""

    IDENTITY = "IDENTITY"
    ROLLFORWARD = "ROLLFORWARD"
    FX = "FX"
    CALENDAR = "CALENDAR"
    SEGMENT = "SEGMENT"


class ReconciliationStatus(str, Enum):
    """Outcome of a reconciliation rule evaluation."""

    PASS = "PASS"  # noqa: S105 - domain status code, not a password
    FAIL = "FAIL"  # noqa: S105 - domain status code, not a password
    WARNING = "WARNING"


# Severity is aligned with the existing MaterialityClass model.
ReconciliationSeverity = MaterialityClass

__all__ = [
    "ReconciliationRuleCategory",
    "ReconciliationStatus",
    "ReconciliationSeverity",
]
