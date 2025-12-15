# src/arche_api/domain/entities/xbrl_override_admin.py
# SPDX-License-Identifier: MIT
"""Admin-facing domain entities for XBRL override rules.

Purpose:
    Represent override rule definitions and their versioned lifecycle in a
    storage-agnostic way suitable for admin tooling. These entities are
    validated by the OverrideRuleValidator and persisted via admin-focused
    repositories.

Layer:
    domain/entities
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass

from arche_api.domain.enums.canonical_statement_metric import CanonicalStatementMetric
from arche_api.domain.services.xbrl_mapping_overrides import OverrideScope

__all__ = ["OverrideRuleDraft", "OverrideRuleVersion"]


@dataclass(frozen=True, slots=True)
class OverrideRuleDraft:
    """User-supplied override rule definition prior to validation.

    Attributes:
        scope:
            Scope for the override rule (GLOBAL, INDUSTRY, COMPANY, ANALYST).
        source_concept:
            XBRL concept QName that this rule targets.
        source_taxonomy:
            Optional taxonomy identifier (e.g., "US_GAAP_2024").
        match_cik:
            CIK constraint when the rule is scoped to a specific company.
        match_industry_code:
            Industry classification constraint for INDUSTRY-scoped rules.
        match_analyst_id:
            Analyst/profile constraint for ANALYST-scoped rules.
        match_dimensions:
            Dimensional constraints represented as axis → member.
        target_metric:
            Canonical metric to remap to, or None for suppression rules.
        is_suppression:
            True when the rule suppresses the metric entirely.
        priority:
            Integer priority used to resolve overlapping rules.
    """

    scope: OverrideScope
    source_concept: str
    source_taxonomy: str | None
    match_cik: str | None
    match_industry_code: str | None
    match_analyst_id: str | None
    match_dimensions: Mapping[str, str]
    target_metric: CanonicalStatementMetric | None
    is_suppression: bool
    priority: int

    def __post_init__(self) -> None:
        """Hook for enforcing invariants on override drafts.

        Implemented as a no-op to align with domain-entity conventions. This
        can be tightened later without changing callers.
        """
        return


@dataclass(frozen=True, slots=True)
class OverrideRuleVersion:
    """Versioned override rule with lifecycle metadata.

    Attributes:
        rule_id:
            Stable identifier for the logical override rule.
        version_sequence:
            Monotonic version sequence for the rule.
        is_active:
            True when this version is the currently active one.
        deprecation_reason:
            Optional human-readable reason for deprecation.
        draft:
            Underlying rule definition for this version.
    """

    rule_id: str
    version_sequence: int
    is_active: bool
    deprecation_reason: str | None
    draft: OverrideRuleDraft

    def __post_init__(self) -> None:
        """Hook for enforcing invariants on versioned rules.

        Implemented as a no-op per domain-entity conventions.
        """
        return
