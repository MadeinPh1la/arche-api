# src/stacklion_api/application/services/xbrl_mapping_overrides.py
# SPDX-License-Identifier: MIT
"""Application service for XBRL mapping override evaluation.

Purpose:
    Provide a thin application-layer facade over the domain-level
    XBRLMappingOverrideEngine and the XBRL mapping overrides repository.

Responsibilities:
    * Retrieve candidate override rules for a given XBRL concept + taxonomy
      from persistence.
    * Delegate deterministic override decisions to the domain engine.
    * Expose a simple interface that application use-cases can call when
      mapping XBRL concepts to canonical metrics.

Layer:
    application/services

Notes:
    This service is intentionally thin. It centralizes the "fetch rules, then
    apply engine" pattern and provides a future-friendly seam for:
        - Caching of rules by concept/taxonomy.
        - Metrics/observability around override usage.
        - Feature-flagged override behaviour.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from typing import Any

from stacklion_api.domain.enums.canonical_statement_metric import (
    CanonicalStatementMetric,
)
from stacklion_api.domain.interfaces.repositories.xbrl_mapping_overrides_repository import (
    XBRLMappingOverridesRepository,
)
from stacklion_api.domain.services.xbrl_mapping_overrides import (
    MappingOverrideRule,
    XBRLMappingOverrideEngine,
)


class XBRLMappingOverridesService:
    """Application-layer facade for XBRL mapping overrides.

    Typical usage from a normalization use-case::

        service = XBRLMappingOverridesService(repository=repo)
        decision, trace = await service.apply_overrides(
            concept=concept,
            taxonomy=taxonomy,
            fact_dimensions=fact_dimensions,
            cik=cik,
            industry_code=industry_code,
            analyst_id=analyst_id,
            base_metric=base_metric,
            debug=False,
        )

    The caller can then use ``decision.final_metric`` as the canonical metric
    to persist or present, falling back to the base metric when no override
    applies.
    """

    def __init__(
        self,
        repository: XBRLMappingOverridesRepository,
        *,
        engine: XBRLMappingOverrideEngine | None = None,
    ) -> None:
        """Initialize the service.

        Args:
            repository:
                Repository used to load XBRL mapping override rules from
                persistence.
            engine:
                Optional domain-level override engine instance. When omitted,
                a new :class:`XBRLMappingOverrideEngine` is constructed.
        """
        self._repository = repository
        self._engine = engine or XBRLMappingOverrideEngine()

    async def list_rules_for_concept(
        self,
        *,
        concept: str,
        taxonomy: str | None = None,
    ) -> Sequence[MappingOverrideRule]:
        """Retrieve candidate override rules for a concept + taxonomy pair.

        Args:
            concept:
                XBRL concept QName (e.g., ``"us-gaap:Revenues"``) for which
                overrides should be evaluated.
            taxonomy:
                Optional taxonomy identifier (e.g., ``"US_GAAP_2024"``). When
                provided, the repository may use it to pre-filter rules while
                still returning taxonomy-agnostic rules.

        Returns:
            Sequence[MappingOverrideRule]: Rules that may be relevant for
            the specified concept/taxonomy. The final eligibility and
            precedence is still determined by the domain engine.
        """
        return await self._repository.list_rules_for_concept(
            concept=concept,
            taxonomy=taxonomy,
        )

    async def apply_overrides(
        self,
        *,
        concept: str,
        taxonomy: str,
        fact_dimensions: Mapping[str, str],
        cik: str,
        industry_code: str | None,
        analyst_id: str | None,
        base_metric: CanonicalStatementMetric | None,
        debug: bool = False,
    ) -> tuple[Any, Any]:
        """Apply override rules for a given XBRL fact context.

        This is the primary entry point for use-cases that already have a
        base canonical metric (from the taxonomy mapping) and wish to apply
        XBRL mapping overrides.

        Args:
            concept:
                XBRL concept QName for the fact being normalized.
            taxonomy:
                Taxonomy identifier (GAAP/IFRS version). Used both for
                repository filtering and for the override engine itself.
            fact_dimensions:
                Mapping of XBRL dimension name → member value for the fact.
                The override engine will treat rule dimensions as a subset
                that must be satisfied by this mapping.
            cik:
                Company CIK for the fact.
            industry_code:
                Industry classification code for the company, if applicable.
            analyst_id:
                Optional analyst/tenant identifier for analyst-scoped rules.
            base_metric:
                Canonical metric produced by the baseline taxonomy mapping
                before overrides are applied. May be ``None`` if there is no
                baseline mapping.
            debug:
                When ``True``, return a rich trace alongside the decision for
                diagnostics and observability.

        Returns:
            Tuple[decision, trace]:
                * decision: The domain-level decision object produced by the
                  override engine. Callers should use ``decision.final_metric``
                  as the effective canonical metric and may inspect
                  ``decision.applied_scope``, ``decision.applied_rule_id``,
                  and ``decision.was_overridden``.
                * trace: Optional trace object describing evaluation details
                  when ``debug=True``; otherwise, may be ``None``.
        """
        rules = await self._repository.list_rules_for_concept(
            concept=concept,
            taxonomy=taxonomy,
        )

        decision, trace = self._engine.apply(
            concept=concept,
            taxonomy=taxonomy,
            fact_dimensions=dict(fact_dimensions),
            cik=cik,
            industry_code=industry_code,
            analyst_id=analyst_id,
            base_metric=base_metric,
            rules=rules,
            debug=debug,
        )
        return decision, trace


__all__ = ["XBRLMappingOverridesService"]
