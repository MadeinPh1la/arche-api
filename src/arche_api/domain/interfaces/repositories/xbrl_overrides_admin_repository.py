# src/arche_api/domain/interfaces/repositories/xbrl_overrides_admin_repository.py
# SPDX-License-Identifier: MIT
"""Admin repository interface for XBRL override rules."""

from __future__ import annotations

from collections.abc import Sequence
from typing import Protocol

from arche_api.domain.entities.xbrl_override_admin import (
    OverrideRuleDraft,
    OverrideRuleVersion,
)


class XBRLOverridesAdminRepository(Protocol):
    """Persistence interface for admin operations on override rules."""

    async def create_rule(self, draft: OverrideRuleDraft) -> OverrideRuleVersion:
        """Create a new override rule and its initial history version."""

    async def update_rule(
        self,
        rule_id: str,
        draft: OverrideRuleDraft,
    ) -> OverrideRuleVersion:
        """Update an existing override rule and append a history version."""

    async def get_rule(self, rule_id: str) -> OverrideRuleVersion | None:
        """Return a single override rule by identity, or None when missing."""

    async def list_rules(
        self,
        *,
        is_active: bool | None = None,
    ) -> Sequence[OverrideRuleVersion]:
        """Return override rules, optionally filtered by active flag."""

    async def deprecate_rule(
        self,
        rule_id: str,
        *,
        reason: str | None = None,
    ) -> OverrideRuleVersion:
        """Mark a rule as deprecated and append a history version."""
