# src/stacklion_api/domain/entities/xbrl_document.py
# Copyright (c)
# SPDX-License-Identifier: MIT
"""XBRL instance document value objects.

Purpose:
    Provide immutable, domain-level representations of the key XBRL
    structures we care about for Phase E10:

        * Periods (instant vs duration).
        * Contexts (entity + period + dimensions).
        * Units.
        * Facts.
        * Linkbase networks (labels, presentation arcs).
        * The overall XBRLDocument container.

Design:
    - All types are frozen dataclasses.
    - Invariants are enforced in __post_init__ hooks.
    - Google-style docstrings with explicit Attributes sections.
"""

from __future__ import annotations

import math
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from datetime import date
from decimal import ROUND_HALF_UP, Decimal, InvalidOperation

# --------------------------------------------------------------------------- #
# Core instance structures                                                    #
# --------------------------------------------------------------------------- #


@dataclass(frozen=True)
class XBRLPeriod:
    """XBRL reporting period.

    Attributes:
        is_instant:
            True if the period represents a single instant in time.
        instant_date:
            Instant date for instant periods; may be None for synthetic or
            partially specified periods.
        start_date:
            Start date for duration periods.
        end_date:
            End date for duration periods.
    """

    is_instant: bool
    instant_date: date | None
    start_date: date | None
    end_date: date | None

    def __post_init__(self) -> None:
        """Validate basic invariants for XBRLPeriod."""
        if self.is_instant:
            # Allow missing instant_date for synthetic contexts, but forbid
            # mixing duration dates with an instant period.
            if self.start_date is not None or self.end_date is not None:
                raise ValueError("start_date/end_date must be None when is_instant is True.")
        else:
            # Duration period: instant_date must not be set.
            if self.instant_date is not None:
                raise ValueError("instant_date must be None for duration periods.")


@dataclass(frozen=True)
class XBRLDimension:
    """XBRL explicit dimension.

    Attributes:
        dimension_qname:
            QName of the dimension (e.g., "us-gaap:StatementClassOfStockAxis").
        member_qname:
            QName of the member (e.g., "us-gaap:CommonStockMember").
    """

    dimension_qname: str
    member_qname: str

    def __post_init__(self) -> None:
        """Validate that dimension and member QNames are non-empty."""
        if not self.dimension_qname.strip():
            raise ValueError("dimension_qname must not be empty.")
        if not self.member_qname.strip():
            raise ValueError("member_qname must not be empty.")


@dataclass(frozen=True)
class XBRLContext:
    """XBRL context describing entity, period, and dimensions.

    Attributes:
        id:
            Context identifier used by facts (contextRef attribute).
        entity_identifier:
            Entity identifier string (e.g., CIK, LEI, etc.).
        period:
            Reporting period for the context.
        dimensions:
            Tuple of explicit dimensions associated with the context.
    """

    id: str
    entity_identifier: str
    period: XBRLPeriod
    dimensions: tuple[XBRLDimension, ...]

    def __post_init__(self) -> None:
        """Validate that the context identifier is non-empty."""
        if not self.id.strip():
            raise ValueError("XBRLContext.id must not be empty.")
        # entity_identifier may be empty for some synthetic contexts; do not
        # enforce a non-empty invariant here.


@dataclass(frozen=True)
class XBRLUnit:
    """XBRL unit description.

    Attributes:
        id:
            Unit identifier (referenced by facts via unitRef).
        measure:
            Measure QName (e.g., "iso4217:USD", "xbrli:pure").
    """

    id: str
    measure: str

    def __post_init__(self) -> None:
        """Validate that unit identifier and measure are non-empty."""
        if not self.id.strip():
            raise ValueError("XBRLUnit.id must not be empty.")
        if not self.measure.strip():
            raise ValueError("XBRLUnit.measure must not be empty.")


@dataclass(frozen=True)
class XBRLFact:
    """XBRL fact value.

    Attributes:
        id:
            Optional fact identifier (may be absent in many instances).
        concept_qname:
            QName of the concept (e.g., "us-gaap:Revenues").
        context_ref:
            ID of the context (contextRef attribute).
        unit_ref:
            ID of the unit (unitRef attribute), or None for unit-less facts.
        raw_value:
            Raw lexical value as found in the instance document.
        decimals:
            Optional decimals hint from the XBRL instance.
        precision:
            Optional precision hint from the XBRL instance.
        is_nil:
            Whether the fact is explicitly nil (xsi:nil="true").
        footnote_refs:
            Tuple of footnote IDs referenced by the fact.
    """

    id: str | None
    concept_qname: str
    context_ref: str
    unit_ref: str | None
    raw_value: str
    decimals: int | None
    precision: int | None
    is_nil: bool
    footnote_refs: tuple[str, ...]

    def __post_init__(self) -> None:
        """Validate that concept and context references are non-empty."""
        if not self.concept_qname.strip():
            raise ValueError("XBRLFact.concept_qname must not be empty.")
        if not self.context_ref.strip():
            raise ValueError("XBRLFact.context_ref must not be empty.")

    def to_decimal(self) -> Decimal | None:
        """Convert the fact's raw value into a Decimal.

        Nil facts return None. For non-nil facts:

        * ``raw_value`` is parsed as a Decimal.
        * If ``decimals`` is provided, the value is quantized using
          ROUND_HALF_UP to the specified number of decimal places.
        * ``precision`` is ignored in E10-A/B.

        Returns:
            Parsed Decimal value, optionally quantized, or None for nil facts.

        Raises:
            ValueError:
                If the raw value cannot be parsed as a Decimal and the fact is
                not marked as nil.
        """
        if self.is_nil:
            return None

        text = self.raw_value.strip()
        if not text:
            return None

        try:
            value = Decimal(text)
        except InvalidOperation as exc:  # pragma: no cover - defensive
            raise ValueError(
                f"Cannot convert XBRLFact.raw_value to Decimal: {self.raw_value!r}"
            ) from exc

        if self.decimals is not None:
            # decimals=2 → quantize to 0.01; decimals=0 → integer, etc.
            quant = Decimal("1").scaleb(-self.decimals)
            value = value.quantize(quant, rounding=ROUND_HALF_UP)

        return value


# --------------------------------------------------------------------------- #
# Linkbase entities (E10-B)                                                   #
# --------------------------------------------------------------------------- #


@dataclass(frozen=True)
class XBRLLabel:
    """XBRL label for a concept.

    Attributes:
        concept_qname:
            QName of the concept this label describes (e.g., "us-gaap:Revenues").
        role:
            Label role URI (e.g., standard, terse, verbose).
        text:
            Human-readable label text as extracted from the linkbase.
    """

    concept_qname: str
    role: str
    text: str

    def __post_init__(self) -> None:
        """Validate that concept, role, and text are non-empty."""
        if not self.concept_qname.strip():
            raise ValueError("XBRLLabel.concept_qname must not be empty.")
        if not self.role.strip():
            raise ValueError("XBRLLabel.role must not be empty.")
        if not self.text.strip():
            raise ValueError("XBRLLabel.text must not be empty.")


@dataclass(frozen=True)
class XBRLPresentationArc:
    """XBRL presentation linkbase arc.

    Attributes:
        role:
            Extended link role URI for this presentation network.
        parent_qname:
            Parent concept QName in the presentation tree.
        child_qname:
            Child concept QName in the presentation tree.
        order:
            Numeric presentation order, used for deterministic sorting.
    """

    role: str
    parent_qname: str
    child_qname: str
    order: float

    def __post_init__(self) -> None:
        """Validate that fields are non-empty and order is finite."""
        if not self.role.strip():
            raise ValueError("XBRLPresentationArc.role must not be empty.")
        if not self.parent_qname.strip():
            raise ValueError("XBRLPresentationArc.parent_qname must not be empty.")
        if not self.child_qname.strip():
            raise ValueError("XBRLPresentationArc.child_qname must not be empty.")
        if not math.isfinite(self.order):
            raise ValueError("XBRLPresentationArc.order must be a finite number.")


@dataclass(frozen=True)
class XBRLLinkbaseNetworks:
    """Aggregated XBRL linkbase networks for an instance.

    Attributes:
        labels_by_concept:
            Mapping from concept QName → tuple of labels for that concept.
        presentation_arcs:
            Tuple of presentation arcs across all extended link roles.
    """

    labels_by_concept: Mapping[str, Sequence[XBRLLabel]] = field(default_factory=dict)
    presentation_arcs: Sequence[XBRLPresentationArc] = field(default_factory=tuple)

    def __post_init__(self) -> None:
        """Normalize collections to immutable structures and validate keys."""
        normalized_labels: dict[str, tuple[XBRLLabel, ...]] = {}
        for concept, labels in self.labels_by_concept.items():
            if not concept.strip():
                raise ValueError("XBRLLinkbaseNetworks labels_by_concept keys must not be empty.")
            normalized_labels[concept] = tuple(labels)

        object.__setattr__(self, "labels_by_concept", normalized_labels)
        object.__setattr__(self, "presentation_arcs", tuple(self.presentation_arcs))


@dataclass(frozen=True)
class XBRLDocument:
    """Parsed XBRL instance document.

    Attributes:
        accession_id:
            EDGAR accession identifier associated with the document.
        contexts:
            Mapping of context ID → XBRLContext.
        units:
            Mapping of unit ID → XBRLUnit.
        facts:
            Sequence of XBRLFact instances contained in the document.
        linkbases:
            Optional XBRLLinkbaseNetworks for labels and presentation arcs.
    """

    accession_id: str
    contexts: Mapping[str, XBRLContext]
    units: Mapping[str, XBRLUnit]
    facts: Sequence[XBRLFact]
    linkbases: XBRLLinkbaseNetworks | None = None

    def __post_init__(self) -> None:
        """Validate that the accession identifier is non-empty."""
        if not self.accession_id.strip():
            raise ValueError("XBRLDocument.accession_id must not be empty.")
        # contexts/units/facts may legitimately be empty for edge cases.


__all__ = [
    "XBRLPeriod",
    "XBRLDimension",
    "XBRLContext",
    "XBRLUnit",
    "XBRLFact",
    "XBRLLabel",
    "XBRLPresentationArc",
    "XBRLLinkbaseNetworks",
    "XBRLDocument",
]
