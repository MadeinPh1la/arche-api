# src/stacklion_api/adapters/mappers/xbrl_parser.py
# Copyright (c) Stacklion.
# SPDX-License-Identifier: MIT
"""XBRL parsing adapter.

Purpose:
    Parse raw XBRL or Inline XBRL XML into pure-domain XBRLDocument structures
    without leaking XML parsing details into the domain or application layers.

Layer:
    adapters/mappers

Notes:
    - E10-A supports a minimal subset of common XBRL shapes.
    - The parser is intentionally conservative and may skip unsupported nodes
      rather than failing aggressively.
"""

from __future__ import annotations

from datetime import date
from typing import cast
from xml.etree.ElementTree import Element  # stdlib typed

from defusedxml import ElementTree as ET

from stacklion_api.domain.entities.xbrl_document import (
    XBRLContext,
    XBRLDimension,
    XBRLDocument,
    XBRLFact,
    XBRLPeriod,
    XBRLUnit,
)


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

        return XBRLDocument(
            accession_id=accession_id,
            contexts=contexts,
            units=units,
            facts=tuple(facts),
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
        ns = "{http://www.xbrl.org/2003/instance}"
        contexts: dict[str, XBRLContext] = {}

        for ctx_elem in root.findall(f".//{ns}context"):
            ctx_id = ctx_elem.attrib.get("id")
            if not ctx_id:
                continue

            identifier_elem = ctx_elem.find(f".//{ns}identifier")
            entity_id = (identifier_elem.text or "").strip() if identifier_elem is not None else ""

            period_elem = ctx_elem.find(f"{ns}period")
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
            segment_elem = ctx_elem.find(f"{ns}segment")
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
        ns = "{http://www.xbrl.org/2003/instance}"

        instant_elem = elem.find(f"{ns}instant")
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

        start_elem = elem.find(f"{ns}startDate")
        end_elem = elem.find(f"{ns}endDate")
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
        ns = "{http://www.xbrl.org/2003/instance}"
        units: dict[str, XBRLUnit] = {}

        for unit_elem in root.findall(f".//{ns}unit"):
            unit_id = unit_elem.attrib.get("id")
            if not unit_id:
                continue

            measure_elem = unit_elem.find(f".//{ns}measure")
            measure_text = (measure_elem.text or "").strip() if measure_elem is not None else ""
            measure = measure_text or "pure"

            units[unit_id] = XBRLUnit(id=unit_id, measure=measure)

        return units

    # ------------------------------------------------------------------ #
    # Fact parsing                                                       #
    # ------------------------------------------------------------------ #

    def _parse_facts(self, root: Element) -> list[XBRLFact]:
        """Parse XBRL facts from the instance tree.

        This E10-A implementation focuses on simple, top-level numeric facts
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
        # are considered candidate facts in E10-A.
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


__all__ = ["XBRLParser"]
