# src/arche_api/domain/interfaces/repositories/xbrl_mapping_overrides_repository.py
# Copyright (c)
# SPDX-License-Identifier: MIT
"""XBRL mapping overrides repository interface.

Purpose:
    Define the domain-level repository contract for loading XBRL mapping
    override rules from persistence into MappingOverrideRule value objects.

Layer:
    domain/interfaces/repositories

Notes:
    - This interface is storage-agnostic and must not depend on SQLAlchemy or
      any other infrastructure concerns.
    - Implementations live in the adapters layer and are wired in via the
      UnitOfWork.
"""

from __future__ import annotations

from collections.abc import Sequence
from typing import Protocol

from arche_api.domain.services.xbrl_mapping_overrides import MappingOverrideRule

__all__ = ["XBRLMappingOverridesRepository"]


class XBRLMappingOverridesRepository(Protocol):
    """Repository interface for XBRL mapping override rules."""

    async def list_all_rules(self) -> Sequence[MappingOverrideRule]:
        """Return all configured override rules.

        This method is suitable for small-to-moderate rule sets where loading
        all rules into memory is acceptable.

        Returns:
            Sequence[MappingOverrideRule]: All override rules known to the
            repository.
        """
        ...

    async def list_rules_for_concept(
        self,
        *,
        concept: str,
        taxonomy: str | None = None,
    ) -> Sequence[MappingOverrideRule]:
        """Return override rules targeting a specific XBRL concept.

        Args:
            concept:
                XBRL concept QName (e.g., "us-gaap:Revenues") for which rules
                should be retrieved.
            taxonomy:
                Optional taxonomy identifier (e.g., "US_GAAP_2024"). When
                provided, implementations may use it to pre-filter rules.
                Taxonomy-agnostic rules (source_taxonomy=None) should still
                be returned.

        Returns:
            Sequence[MappingOverrideRule]: Override rules that may be relevant
            for the requested concept and taxonomy.

        Notes:
            The domain-level override engine remains responsible for applying
            the final taxonomy and scope matching rules. Repository
            implementations should err on the side of returning a superset of
            candidates rather than filtering too aggressively.
        """
        ...
