# src/stacklion_api/domain/services/gaap_taxonomy.py
# Copyright (c)
# SPDX-License-Identifier: MIT
"""Minimal GAAP taxonomy for XBRL normalization.

Purpose:
    Provide a pure-domain representation of a minimal GAAP taxonomy used for
    validating XBRL facts and, where appropriate, resolving canonical metrics.

Layer:
    domain/services

Notes:
    - No network I/O or dynamic downloads.
    - E10-A only covers Tier 1 concepts used by the canonical metric registry
      in the EDGAR normalization engine.
    - Validation is deliberately minimal and focused on period type and units.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass

from stacklion_api.domain.entities.xbrl_document import (
    XBRLContext,
    XBRLFact,
    XBRLUnit,
)
from stacklion_api.domain.enums.canonical_statement_metric import CanonicalStatementMetric
from stacklion_api.domain.exceptions.edgar import EdgarMappingError


@dataclass(frozen=True)
class GAAPConcept:
    """Minimal GAAP taxonomy concept metadata.

    Attributes:
        concept_qname:
            Qualified concept name (e.g., "us-gaap:Revenues").
        canonical_metric:
            Optional canonical metric this concept maps to. None for concepts
            that are out-of-scope for Tier 1 metrics.
        period_type:
            Expected period type: "instant" or "duration".
        default_unit_suffix:
            Expected unit suffix for the concept (e.g., "USD"), or None when
            any unit is acceptable.
        allowed_dimensions:
            Tuple of allowed dimension qnames for the concept. E10-A uses this
            primarily as a placeholder for later segment/geographic rules.
    """

    concept_qname: str
    canonical_metric: CanonicalStatementMetric | None
    period_type: str
    default_unit_suffix: str | None
    allowed_dimensions: Sequence[str]


class GAAPTaxonomy:
    """Minimal GAAP taxonomy for XBRL validation and metric resolution."""

    def __init__(self, concepts: Mapping[str, GAAPConcept]) -> None:
        """Initialize the taxonomy.

        Args:
            concepts:
                Mapping from concept qname to GAAPConcept metadata.
        """
        self._concepts = concepts

    def get(self, qname: str) -> GAAPConcept | None:
        """Return the GAAPConcept associated with a qname, if any."""
        return self._concepts.get(qname)

    def resolve_metric(self, qname: str) -> CanonicalStatementMetric | None:
        """Resolve the canonical metric for a concept, if defined."""
        concept = self._concepts.get(qname)
        return concept.canonical_metric if concept is not None else None

    # --------------------------------------------------------------------- #
    # Validation helpers                                                    #
    # --------------------------------------------------------------------- #

    def validate_fact(
        self,
        *,
        fact: XBRLFact,
        context: XBRLContext,
        unit: XBRLUnit | None,
    ) -> None:
        """Validate a single XBRL fact against the taxonomy.

        Validation rules (E10-A scope):
            * If the concept is unknown, no validation is performed.
            * If period_type is "instant", the context period must be instant.
            * If period_type is "duration", the context period must be a
              duration.
            * If default_unit_suffix is set and a unit is provided, the unit
              measure should end with that suffix (e.g., "USD").

        Args:
            fact:
                XBRLFact to validate.
            context:
                XBRLContext referenced by the fact.
            unit:
                XBRLUnit referenced by the fact, if any.

        Raises:
            EdgarMappingError:
                If the fact violates taxonomy-defined invariants.
        """
        concept = self._concepts.get(fact.concept_qname)
        if concept is None:
            # Out-of-scope concept; do not enforce additional rules in E10-A.
            return

        # Period type
        if concept.period_type == "instant" and not context.period.is_instant:
            raise EdgarMappingError(
                "GAAP taxonomy period_type mismatch: expected instant period.",
                details={"concept": concept.concept_qname, "context_id": context.id},
            )

        if concept.period_type == "duration" and context.period.is_instant:
            raise EdgarMappingError(
                "GAAP taxonomy period_type mismatch: expected duration period.",
                details={"concept": concept.concept_qname, "context_id": context.id},
            )

        # Unit suffix (best-effort, not exhaustive)
        if concept.default_unit_suffix and unit is not None:
            measure = (unit.measure or "").upper()
            if not measure.endswith(concept.default_unit_suffix.upper()):
                raise EdgarMappingError(
                    "GAAP taxonomy unit mismatch for concept.",
                    details={
                        "concept": concept.concept_qname,
                        "expected_unit_suffix": concept.default_unit_suffix,
                        "actual_measure": unit.measure,
                    },
                )


def build_minimal_gaap_taxonomy() -> GAAPTaxonomy:
    """Build the minimal GAAP taxonomy for E10-A Tier 1 metrics.

    The mapping here is intentionally small and driven by the canonical metric
    registry in the EDGAR normalization engine. Additional concepts can be
    added in later phases without breaking existing behavior.

    Returns:
        GAAPTaxonomy instance loaded with Tier 1 GAAP concepts.
    """
    concepts: dict[str, GAAPConcept] = {}

    def add(
        concept_qname: str,
        metric: CanonicalStatementMetric | None,
        period_type: str,
        default_unit_suffix: str | None,
    ) -> None:
        concepts[concept_qname] = GAAPConcept(
            concept_qname=concept_qname,
            canonical_metric=metric,
            period_type=period_type,
            default_unit_suffix=default_unit_suffix,
            allowed_dimensions=(),
        )

    # Income statement (duration)
    add("us-gaap:Revenues", CanonicalStatementMetric.REVENUE, "duration", "USD")
    add("us-gaap:NetIncomeLoss", CanonicalStatementMetric.NET_INCOME, "duration", "USD")
    add(
        "us-gaap:OperatingIncomeLoss",
        CanonicalStatementMetric.OPERATING_INCOME,
        "duration",
        "USD",
    )

    # Balance sheet (instant)
    add("us-gaap:Assets", CanonicalStatementMetric.TOTAL_ASSETS, "instant", "USD")
    add(
        "us-gaap:Liabilities",
        CanonicalStatementMetric.TOTAL_LIABILITIES,
        "instant",
        "USD",
    )

    # Cash flow (duration)
    add(
        "us-gaap:NetCashProvidedByUsedInOperatingActivities",
        CanonicalStatementMetric.NET_CASH_FROM_OPERATING_ACTIVITIES,
        "duration",
        "USD",
    )

    # Additional Tier 1 concepts can be extended here as needed.

    return GAAPTaxonomy(concepts)
