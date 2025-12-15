# src/arche_api/domain/services/xbrl_override_validator.py
# SPDX-License-Identifier: MIT
"""Validation service for XBRL override rules.

Purpose:
    Provide domain-level validation for XBRL override rules before they are
    persisted or mutated by admin workflows. This keeps business invariants
    close to the domain and independent of persistence or HTTP concerns.

Layer:
    domain/services
"""

from __future__ import annotations

from arche_api.domain.entities.xbrl_override_admin import (
    OverrideRuleDraft,
    OverrideRuleVersion,
)
from arche_api.domain.exceptions.edgar import EdgarMappingError
from arche_api.domain.services.xbrl_mapping_overrides import OverrideScope

__all__ = ["OverrideRuleValidator"]


class OverrideRuleValidator:
    """Validate override rule drafts for create/update/deprecate operations."""

    def validate_for_create(self, draft: OverrideRuleDraft) -> None:
        """Validate a new override rule draft.

        Args:
            draft:
                Rule definition proposed for creation.

        Raises:
            EdgarMappingError:
                When the draft violates scope, dimensional, or priority rules.
        """
        self._validate_scope_constraints(draft)
        self._validate_match_dimensions(draft)
        self._validate_priority(draft)

    def validate_for_update(
        self,
        existing: OverrideRuleVersion,
        draft: OverrideRuleDraft,
    ) -> None:
        """Validate an update to an existing override rule.

        Args:
            existing:
                Current persisted version of the override rule.
            draft:
                Proposed updated definition for the rule.

        Raises:
            EdgarMappingError:
                When the updated draft violates scope, dimensional, or
                priority rules.
        """
        self._validate_scope_constraints(draft)
        self._validate_match_dimensions(draft)
        self._validate_priority(draft)

    def validate_for_deprecate(self, existing: OverrideRuleVersion) -> None:
        """Validate that a rule can be deprecated.

        Args:
            existing:
                Current persisted version of the override rule.

        Notes:
            Currently a no-op. This hook exists so that future lifecycle
            constraints (for example, preventing deprecation of rules in use
            by active configurations) can be enforced without changing the
            admin callers.
        """
        return

    # --------------------------------------------------------------------- #
    # Internal helpers                                                      #
    # --------------------------------------------------------------------- #

    def _validate_scope_constraints(self, draft: OverrideRuleDraft) -> None:
        """Enforce scope-specific match-field constraints.

        Args:
            draft:
                Rule definition to validate.

        Raises:
            EdgarMappingError:
                When the scope-specific invariants are violated.
        """
        scope = draft.scope

        if scope is OverrideScope.GLOBAL:
            self._validate_global_scope(draft)
        elif scope is OverrideScope.INDUSTRY:
            self._validate_industry_scope(draft)
        elif scope is OverrideScope.COMPANY:
            self._validate_company_scope(draft)
        elif scope is OverrideScope.ANALYST:
            self._validate_analyst_scope(draft)

        if draft.is_suppression and draft.target_metric is not None:
            raise EdgarMappingError(
                "Suppression override rules must not specify target_metric.",
            )

    def _validate_global_scope(self, draft: OverrideRuleDraft) -> None:
        """Validate GLOBAL scope invariants.

        GLOBAL rules must not specify company, industry, or analyst-specific
        match fields.
        """
        if any((draft.match_cik, draft.match_industry_code, draft.match_analyst_id)):
            raise EdgarMappingError(
                "GLOBAL override rules must not specify match_cik, "
                "match_industry_code, or match_analyst_id.",
            )

    def _validate_industry_scope(self, draft: OverrideRuleDraft) -> None:
        """Validate INDUSTRY scope invariants.

        INDUSTRY rules must specify an industry code and may not specify a
        company-specific match_cik.
        """
        if not draft.match_industry_code:
            raise EdgarMappingError(
                "INDUSTRY override rules must specify match_industry_code.",
            )
        if draft.match_cik:
            raise EdgarMappingError(
                "INDUSTRY override rules must not specify match_cik.",
            )

    def _validate_company_scope(self, draft: OverrideRuleDraft) -> None:
        """Validate COMPANY scope invariants.

        COMPANY rules must specify a company CIK.
        """
        if not draft.match_cik:
            raise EdgarMappingError(
                "COMPANY override rules must specify match_cik.",
            )

    def _validate_analyst_scope(self, draft: OverrideRuleDraft) -> None:
        """Validate ANALYST scope invariants.

        ANALYST rules must specify an analyst or profile identifier.
        """
        if not draft.match_analyst_id:
            raise EdgarMappingError(
                "ANALYST override rules must specify match_analyst_id.",
            )

    def _validate_match_dimensions(self, draft: OverrideRuleDraft) -> None:
        """Ensure match_dimensions mapping is well-formed.

        Args:
            draft:
                Rule definition whose dimensional constraints should be
                validated.

        Raises:
            EdgarMappingError:
                When dimension keys or values are empty or malformed.
        """
        dims = draft.match_dimensions or {}
        for key, value in dims.items():
            if not key or not key.strip():
                raise EdgarMappingError("match_dimensions keys must be non-empty strings.")
            if not value or not value.strip():
                raise EdgarMappingError("match_dimensions values must be non-empty strings.")

    def _validate_priority(self, draft: OverrideRuleDraft) -> None:
        """Validate rule priority.

        Args:
            draft:
                Rule definition whose priority should be validated.

        Raises:
            EdgarMappingError:
                When the priority is negative.
        """
        if draft.priority < 0:
            raise EdgarMappingError("priority must be non-negative for override rules.")
