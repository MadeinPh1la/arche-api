# src/arche_api/adapters/mappers/xbrl_parser.py
# Copyright (c) Arche.
# SPDX-License-Identifier: MIT
"""XBRL parsing adapter.

Purpose:
    Parse raw XBRL or Inline XBRL XML into pure-domain XBRLDocument structures
    without leaking XML parsing details into the domain or application layers.

Layer:
    adapters/mappers

Notes:
    - Instance parsing covers:
        * Contexts (entity, period, dimensions).
        * Units.
        * Simple numeric facts.
    - E10-B extends this adapter with **in-document linkbase parsing**:
        * labelLink → XBRLLabel, grouped by concept.
        * presentationLink → XBRLPresentationArc chains by extended link role.
    - External taxonomy packages / linkbaseRef resolution are deliberately
      out-of-scope for this phase; only linkbase XML embedded in the filing
      is parsed.
    - The parser is intentionally conservative and may skip unsupported nodes
      rather than failing aggressively.
"""

from __future__ import annotations

from datetime import date
from typing import cast
from xml.etree.ElementTree import Element  # stdlib typed

from defusedxml import ElementTree as ET

from arche_api.domain.entities.xbrl_document import (
    XBRLContext,
    XBRLDimension,
    XBRLDocument,
    XBRLFact,
    XBRLLabel,
    XBRLLinkbaseNetworks,
    XBRLPeriod,
    XBRLPresentationArc,
    XBRLUnit,
)

# Namespace constants used in XBRL / linkbase documents.
_XBRLI_NS = "{http://www.xbrl.org/2003/instance}"
_LINK_NS = "{http://www.xbrl.org/2003/linkbase}"
_XLINK_HREF = "{http://www.w3.org/1999/xlink}href"
_XLINK_LABEL = "{http://www.w3.org/1999/xlink}label"
_XLINK_ROLE = "{http://www.w3.org/1999/xlink}role"
_XLINK_TYPE = "{http://www.w3.org/1999/xlink}type"
_XLINK_FROM = "{http://www.w3.org/1999/xlink}from"
_XLINK_TO = "{http://www.w3.org/1999/xlink}to"


def _concept_qname(elem: Element) -> str:
    """Build a best-effort QName for an XBRL fact element.

    Behavior:
        * If the tag is in Clark notation ("{uri}LocalName"), derive a prefix
          heuristically from the namespace URI:
              - URIs containing "us-gaap" → "us-gaap"
              - URIs containing "ifrs" → "ifrs-full"
        * Otherwise, fall back to the raw tag.

    Args:
        elem:
            XML element representing the fact.

    Returns:
        QName string such as "us-gaap:Revenues" or "ifrs-full:Revenue".
    """
    tag = elem.tag
    if tag.startswith("{"):
        uri, local = tag[1:].split("}", 1)
        uri_lower = uri.lower()
        if "us-gaap" in uri_lower:
            return f"us-gaap:{local}"
        if "ifrs" in uri_lower:
            return f"ifrs-full:{local}"
        return local
    return tag


def _concept_qname_from_href(href: str) -> str | None:
    """Best-effort concept QName extraction from a linkbase href.

    Typical href shapes seen in GAAP linkbases:

        * "us-gaap-2024-01-31.xsd#us-gaap_Revenues"
        * "foo.xsd#Revenues"
        * "foo.xsd#us-gaap:Revenues"

    We try, in order:

        * Fragment with an explicit prefix ("us-gaap:Revenues") → use as-is.
        * Fragment of the form "us-gaap_Revenues" → rewrite first "_" as ":".
        * Otherwise return the fragment unchanged.

    Args:
        href:
            xlink:href attribute from a link:loc element.

    Returns:
        A QName string or None if it cannot be determined.
    """
    if "#" not in href:
        return None

    fragment = href.split("#", 1)[1]
    fragment = fragment.strip()
    if not fragment:
        return None

    if ":" in fragment:
        # Already looks like a QName.
        return fragment

    if "_" in fragment:
        prefix, local = fragment.split("_", 1)
        if prefix and local:
            return f"{prefix}:{local}"

    return fragment or None


class XBRLParser:
    """Parse raw XBRL XML content into an :class:`XBRLDocument`.

    This adapter is responsible for turning low-level XML instances into
    domain-level value objects without exposing XML concerns to callers.
    """

    def parse(self, *, accession_id: str, content: bytes | str) -> XBRLDocument:
        """Parse the provided XBRL content.

        Args:
            accession_id:
                EDGAR accession identifier associated with the document.
            content:
                Raw XML content as bytes or string.

        Returns:
            Parsed :class:`XBRLDocument` instance.

        Raises:
            ValueError:
                If the XML content cannot be parsed.
        """
        if isinstance(content, bytes):
            root = cast(Element, ET.fromstring(content))
        else:
            root = cast(Element, ET.fromstring(content.encode("utf-8")))

        contexts = self._parse_contexts(root)
        units = self._parse_units(root)
        facts = self._parse_facts(root)
        linkbases = self._parse_linkbases(root)

        return XBRLDocument(
            accession_id=accession_id,
            contexts=contexts,
            units=units,
            facts=tuple(facts),
            linkbases=linkbases,
        )

    # ------------------------------------------------------------------ #
    # Context parsing                                                    #
    # ------------------------------------------------------------------ #

    def _parse_contexts(self, root: Element) -> dict[str, XBRLContext]:
        """Parse XBRL contexts from the instance tree.

        Args:
            root:
                Root XML element of the XBRL instance.

        Returns:
            Mapping from context ID to :class:`XBRLContext` instances.
        """
        contexts: dict[str, XBRLContext] = {}

        for ctx_elem in root.findall(f".//{_XBRLI_NS}context"):
            ctx_id = ctx_elem.attrib.get("id")
            if not ctx_id:
                continue

            identifier_elem = ctx_elem.find(f".//{_XBRLI_NS}identifier")
            entity_id = (identifier_elem.text or "").strip() if identifier_elem is not None else ""

            period_elem = ctx_elem.find(f"{_XBRLI_NS}period")
            period = (
                self._parse_period(period_elem)
                if period_elem is not None
                else XBRLPeriod(
                    is_instant=False,
                    instant_date=None,
                    start_date=None,
                    end_date=None,
                )
            )

            dimensions: list[XBRLDimension] = []
            segment_elem = ctx_elem.find(f"{_XBRLI_NS}segment")
            if segment_elem is not None:
                for dim_elem in segment_elem:
                    dim_qname = dim_elem.attrib.get("dimension")
                    member_text = (dim_elem.text or "").strip()
                    if dim_qname and member_text:
                        dimensions.append(
                            XBRLDimension(
                                dimension_qname=dim_qname,
                                member_qname=member_text,
                            )
                        )

            contexts[ctx_id] = XBRLContext(
                id=ctx_id,
                entity_identifier=entity_id,
                period=period,
                dimensions=tuple(dimensions),
            )

        return contexts

    def _parse_period(self, elem: Element) -> XBRLPeriod:
        """Parse an XBRL period element into an :class:`XBRLPeriod`.

        Args:
            elem:
                XML element representing the period.

        Returns:
            Parsed :class:`XBRLPeriod` instance.
        """
        instant_elem = elem.find(f"{_XBRLI_NS}instant")
        if instant_elem is not None:
            instant_text = (instant_elem.text or "").strip()
            if instant_text:
                instant = date.fromisoformat(instant_text)
                return XBRLPeriod(
                    is_instant=True,
                    instant_date=instant,
                    start_date=None,
                    end_date=None,
                )

        start_elem = elem.find(f"{_XBRLI_NS}startDate")
        end_elem = elem.find(f"{_XBRLI_NS}endDate")
        start: date | None = None
        end: date | None = None

        if start_elem is not None:
            start_text = (start_elem.text or "").strip()
            if start_text:
                start = date.fromisoformat(start_text)
        if end_elem is not None:
            end_text = (end_elem.text or "").strip()
            if end_text:
                end = date.fromisoformat(end_text)

        return XBRLPeriod(
            is_instant=False,
            instant_date=None,
            start_date=start,
            end_date=end,
        )

    # ------------------------------------------------------------------ #
    # Unit parsing                                                       #
    # ------------------------------------------------------------------ #

    def _parse_units(self, root: Element) -> dict[str, XBRLUnit]:
        """Parse XBRL unit definitions from the instance tree.

        Args:
            root:
                Root XML element of the XBRL instance.

        Returns:
            Mapping from unit ID to :class:`XBRLUnit` instances.
        """
        units: dict[str, XBRLUnit] = {}

        for unit_elem in root.findall(f".//{_XBRLI_NS}unit"):
            unit_id = unit_elem.attrib.get("id")
            if not unit_id:
                continue

            measure_elem = unit_elem.find(f".//{_XBRLI_NS}measure")
            measure_text = (measure_elem.text or "").strip() if measure_elem is not None else ""
            measure = measure_text or "pure"

            units[unit_id] = XBRLUnit(id=unit_id, measure=measure)

        return units

    # ------------------------------------------------------------------ #
    # Fact parsing                                                       #
    # ------------------------------------------------------------------ #

    def _parse_facts(self, root: Element) -> list[XBRLFact]:
        """Parse XBRL facts from the instance tree.

        This implementation focuses on simple, top-level numeric facts
        and ignores tuples, footnotes, and complex typed dimensions.

        Args:
            root:
                Root XML element of the XBRL instance.

        Returns:
            List of :class:`XBRLFact` instances parsed from the document.
        """
        facts: list[XBRLFact] = []

        xsi_nil_attr = "{http://www.w3.org/2001/XMLSchema-instance}nil"

        # Only top-level children in the instance namespace or with a prefix
        # are considered candidate facts here.
        for elem in root:
            tag = elem.tag
            if "}" not in tag:
                continue

            # Skip structural instance elements.
            if tag.endswith("context") or tag.endswith("unit"):
                continue

            concept_qname = _concept_qname(elem)
            context_ref = elem.attrib.get("contextRef")
            if not context_ref:
                continue

            unit_ref = elem.attrib.get("unitRef")
            decimals_raw = elem.attrib.get("decimals")
            precision_raw = elem.attrib.get("precision")
            is_nil = elem.attrib.get(xsi_nil_attr) == "true"
            raw_value = (elem.text or "").strip()

            decimals = (
                int(decimals_raw) if decimals_raw is not None and decimals_raw.isdigit() else None
            )
            precision = (
                int(precision_raw)
                if precision_raw is not None and precision_raw.isdigit()
                else None
            )

            facts.append(
                XBRLFact(
                    id=elem.attrib.get("id"),
                    concept_qname=concept_qname,
                    context_ref=context_ref,
                    unit_ref=unit_ref,
                    raw_value=raw_value,
                    decimals=decimals,
                    precision=precision,
                    is_nil=is_nil,
                    footnote_refs=(),
                )
            )

        return facts

    # ------------------------------------------------------------------ #
    # Linkbase parsing (E10-B)                                          #
    # ------------------------------------------------------------------ #

    def _parse_linkbases(self, root: Element) -> XBRLLinkbaseNetworks:
        """Parse label and presentation linkbase networks from the document.

        Behavior:
            - Parses all embedded link:labelLink and link:presentationLink
              elements.
            - Resolves concept QNames from loc href fragments.
            - Resolves labels via labelArc (loc → label resource).
            - Builds deterministic presentation arcs keyed by extended link role.

        Args:
            root:
                Root XML element of the XBRL (or Inline XBRL) document.

        Returns:
            XBRLLinkbaseNetworks instance; empty if no linkbase content exists.
        """
        labels_by_concept = self._parse_label_linkbases(root)
        presentation_arcs = self._parse_presentation_linkbases(root)

        # Normalize to immutable structures expected by the domain.
        frozen_labels: dict[str, tuple[XBRLLabel, ...]] = {
            concept: tuple(labels) for concept, labels in labels_by_concept.items()
        }

        return XBRLLinkbaseNetworks(
            labels_by_concept=frozen_labels,
            presentation_arcs=tuple(presentation_arcs),
        )

    def _parse_label_linkbases(self, root: Element) -> dict[str, list[XBRLLabel]]:
        """Parse label linkbases into a mapping of concept → labels."""
        result: dict[str, list[XBRLLabel]] = {}

        for label_link in root.findall(f".//{_LINK_NS}labelLink"):
            # Map locator labels → concept QNames.
            loc_concepts: dict[str, str] = {}
            for loc in label_link.findall(f"{_LINK_NS}loc"):
                loc_label = loc.attrib.get(_XLINK_LABEL)
                href = loc.attrib.get(_XLINK_HREF, "")
                concept_qname = _concept_qname_from_href(href) if href else None
                if loc_label and concept_qname:
                    loc_concepts[loc_label] = concept_qname

            # Map label resource labels → (role, text).
            label_resources: dict[str, tuple[str, str]] = {}
            for label in label_link.findall(f"{_LINK_NS}label"):
                if label.attrib.get(_XLINK_TYPE) != "resource":
                    continue

                res_label = label.attrib.get(_XLINK_LABEL)
                role = label.attrib.get(_XLINK_ROLE, "")
                text = (label.text or "").strip()
                if res_label and text:
                    label_resources[res_label] = (role, text)

            # Connect locs to label resources via labelArc.
            for arc in label_link.findall(f"{_LINK_NS}labelArc"):
                from_label = arc.attrib.get(_XLINK_FROM)
                to_label = arc.attrib.get(_XLINK_TO)
                if not from_label or not to_label:
                    continue

                concept_qname = loc_concepts.get(from_label)
                label_meta = label_resources.get(to_label)
                if not concept_qname or not label_meta:
                    continue

                role, text = label_meta
                label_obj = XBRLLabel(
                    concept_qname=concept_qname,
                    role=role,
                    text=text,
                )
                result.setdefault(concept_qname, []).append(label_obj)

        return result

    def _parse_presentation_linkbases(self, root: Element) -> list[XBRLPresentationArc]:
        """Parse presentation linkbases into a flat list of arcs."""
        arcs: list[XBRLPresentationArc] = []

        for pres_link in root.findall(f".//{_LINK_NS}presentationLink"):
            role = pres_link.attrib.get(_XLINK_ROLE, "")

            # Map locator labels → concept QNames.
            loc_concepts: dict[str, str] = {}
            for loc in pres_link.findall(f"{_LINK_NS}loc"):
                loc_label = loc.attrib.get(_XLINK_LABEL)
                href = loc.attrib.get(_XLINK_HREF, "")
                concept_qname = _concept_qname_from_href(href) if href else None
                if loc_label and concept_qname:
                    loc_concepts[loc_label] = concept_qname

            for arc in pres_link.findall(f"{_LINK_NS}presentationArc"):
                from_label = arc.attrib.get(_XLINK_FROM)
                to_label = arc.attrib.get(_XLINK_TO)
                if not from_label or not to_label:
                    continue

                parent_qname = loc_concepts.get(from_label)
                child_qname = loc_concepts.get(to_label)
                if not parent_qname or not child_qname:
                    continue

                order_raw = arc.attrib.get("order", "0")
                try:
                    order = float(order_raw)
                except ValueError:
                    # Bad order values are ignored rather than failing parsing.
                    continue

                arcs.append(
                    XBRLPresentationArc(
                        role=role,
                        parent_qname=parent_qname,
                        child_qname=child_qname,
                        order=order,
                    )
                )

        return arcs


__all__ = ["XBRLParser"]
