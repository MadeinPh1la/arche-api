# src/arche_api/domain/entities/edgar_dq.py
# Copyright (c) Arche.
# SPDX-License-Identifier: MIT
"""EDGAR data-quality entities.

Purpose:
    Define domain entities used by the EDGAR data-quality (DQ) layer,
    including statement identities, DQ runs, fact-level quality flags, and
    rule-level anomalies.

Layer:
    domain/entities

Notes:
    - These entities are storage-agnostic and suitable for use by domain
      services and application use cases.
    - Severity is represented using MaterialityClass to align with the
      broader analytics and restatement severity model.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from datetime import datetime
from typing import Any

from arche_api.domain.enums.edgar import FiscalPeriod, MaterialityClass, StatementType

__all__ = [
    "NormalizedStatementIdentity",
    "EdgarDQRun",
    "EdgarFactQuality",
    "EdgarDQAnomaly",
]


@dataclass(frozen=True, slots=True)
class NormalizedStatementIdentity:
    """Identity tuple for a normalized statement version.

    Attributes:
        cik:
            Central Index Key for the filer.
        statement_type:
            Statement type (income statement, balance sheet, etc.).
        fiscal_year:
            Fiscal year associated with the statement.
        fiscal_period:
            Fiscal period within the year (e.g., FY, Q1, Q2).
        version_sequence:
            Statement version sequence. This is the same sequence used by
            normalized payloads and fact derivation.
    """

    cik: str
    statement_type: StatementType
    fiscal_year: int
    fiscal_period: FiscalPeriod
    version_sequence: int

    def __post_init__(self) -> None:
        """Hook for enforcing invariants on statement identities.

        Currently a minimal no-op implementation that satisfies the domain
        entity conventions. This can be extended in the future to assert
        stronger invariants without changing the public API.
        """
        # Intentionally no strict validation to avoid breaking existing callers.
        return


@dataclass(frozen=True, slots=True)
class EdgarDQRun:
    """Data-quality evaluation run metadata.

    Attributes:
        dq_run_id:
            Stable identifier for this DQ run.
        statement_identity:
            Identity of the statement that was evaluated. For future
            extensions, this may be None for broader scopes (e.g., batch runs).
        rule_set_version:
            Version identifier for the set of DQ rules applied (e.g., "v1").
        scope_type:
            High-level scope for the run (e.g., "STATEMENT", "COMPANY").
        executed_at:
            Timestamp at which the evaluation completed.
    """

    dq_run_id: str
    statement_identity: NormalizedStatementIdentity | None
    rule_set_version: str
    scope_type: str
    executed_at: datetime

    def __post_init__(self) -> None:
        """Hook for enforcing invariants on DQ run entities.

        The implementation is intentionally minimal to avoid introducing
        behavioral changes. It exists primarily to satisfy architectural
        conventions and may be extended with stricter checks later.
        """
        return


@dataclass(frozen=True, slots=True)
class EdgarFactQuality:
    """Fact-level quality flags and severity classification.

    Attributes:
        dq_run_id:
            Identifier of the DQ run that produced this record.
        statement_identity:
            Identity of the statement version to which the fact belongs.
        metric_code:
            Canonical metric code (e.g., "REVENUE").
        dimension_key:
            Deterministic key representing the dimensional slice.
        severity:
            Severity classification for the fact under the applied rules.
        is_present:
            Whether the fact is present in the normalized payload.
        is_non_negative:
            Whether the fact satisfies a non-negativity constraint, when
            applicable. None when the rule is not applicable.
        is_consistent_with_history:
            Whether the fact is considered consistent with historical values,
            when such a rule is applied. None when no history-based rule was
            evaluated for this fact.
        has_known_issue:
            Whether the fact is associated with a known or previously flagged
            issue outside of automatic rules.
        details:
            Optional machine-readable details, such as rule contributions to
            the overall severity for this fact.
    """

    dq_run_id: str
    statement_identity: NormalizedStatementIdentity
    metric_code: str
    dimension_key: str

    severity: MaterialityClass

    is_present: bool
    is_non_negative: bool | None
    is_consistent_with_history: bool | None
    has_known_issue: bool

    details: Mapping[str, Any] | None

    def __post_init__(self) -> None:
        """Hook for enforcing invariants on fact-quality entities.

        Currently implemented as a no-op to avoid impacting existing logic.
        It can be tightened later (for example to assert non-empty metric
        codes) once the DQ pipeline is fully stabilized.
        """
        return


@dataclass(frozen=True, slots=True)
class EdgarDQAnomaly:
    """Single DQ rule anomaly.

    Attributes:
        dq_run_id:
            Identifier of the DQ run that produced this anomaly.
        statement_identity:
            Identity of the affected statement version, when applicable.
        metric_code:
            Canonical metric code affected by the anomaly, when applicable.
        dimension_key:
            Dimensional slice key affected by the anomaly, when applicable.
        rule_code:
            Stable code for the rule that triggered the anomaly
            (e.g., "NEGATIVE_REVENUE").
        severity:
            Severity classification of the anomaly.
        message:
            Human-readable description of the anomaly.
        details:
            Optional machine-readable payload with additional context
            (e.g., observed value, expected range, historical statistics).
    """

    dq_run_id: str
    statement_identity: NormalizedStatementIdentity | None
    metric_code: str | None
    dimension_key: str | None
    rule_code: str
    severity: MaterialityClass
    message: str
    details: Mapping[str, Any] | None

    def __post_init__(self) -> None:
        """Hook for enforcing invariants on anomaly entities.

        This is intentionally a no-op that fulfills domain-entity conventions.
        Stricter validation can be layered on later if needed.
        """
        return
