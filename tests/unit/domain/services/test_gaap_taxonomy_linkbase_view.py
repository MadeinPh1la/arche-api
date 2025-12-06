# tests/unit/domain/services/test_gaap_taxonomy_linkbase_view.py
# Copyright (c)
# SPDX-License-Identifier: MIT
"""Tests for GaapTaxonomyView linkbase behavior."""

from __future__ import annotations

from stacklion_api.domain.entities.xbrl_document import (
    XBRLLabel,
    XBRLLinkbaseNetworks,
    XBRLPresentationArc,
)
from stacklion_api.domain.services.gaap_taxonomy import GaapTaxonomyView, PresentationNode


def _build_linkbases_for_labels() -> XBRLLinkbaseNetworks:
    """Helper: construct linkbases with multiple labels for one concept."""
    labels = (
        XBRLLabel(
            concept_qname="us-gaap:Revenues",
            role="http://www.xbrl.org/2003/role/terseLabel",
            text="Revenue (terse)",
        ),
        XBRLLabel(
            concept_qname="us-gaap:Revenues",
            role="http://www.xbrl.org/2003/role/label",
            text="Revenues",
        ),
    )

    return XBRLLinkbaseNetworks(
        labels_by_concept={"us-gaap:Revenues": labels},
        presentation_arcs=(),
    )


def _build_linkbases_for_presentation() -> XBRLLinkbaseNetworks:
    """Helper: construct a simple income statement presentation network."""
    # role-income-statement:
    #   Revenues
    #       → OperatingIncomeLoss
    #           → NetIncomeLoss
    arcs = (
        XBRLPresentationArc(
            role="role-income-statement",
            parent_qname="us-gaap:Revenues",
            child_qname="us-gaap:OperatingIncomeLoss",
            order=2.0,
        ),
        XBRLPresentationArc(
            role="role-income-statement",
            parent_qname="us-gaap:OperatingIncomeLoss",
            child_qname="us-gaap:NetIncomeLoss",
            order=3.0,
        ),
    )

    return XBRLLinkbaseNetworks(
        labels_by_concept={},
        presentation_arcs=arcs,
    )


def test_gaap_taxonomy_view_get_best_label_prefers_requested_roles() -> None:
    """get_best_label should honor preferred_roles ordering and fall back."""
    linkbases = _build_linkbases_for_labels()
    view = GaapTaxonomyView(linkbases=linkbases)

    # Prefer standard label over terse.
    label = view.get_best_label(
        concept_qname="us-gaap:Revenues",
        preferred_roles=("http://www.xbrl.org/2003/role/label",),
    )
    assert label == "Revenues"

    # Prefer terse label when that role is first.
    label_terse_first = view.get_best_label(
        concept_qname="us-gaap:Revenues",
        preferred_roles=("http://www.xbrl.org/2003/role/terseLabel",),
    )
    assert label_terse_first == "Revenue (terse)"

    # If no roles specified, any label is acceptable but must be non-empty.
    any_label = view.get_best_label("us-gaap:Revenues")
    assert any_label is not None
    assert any_label != ""


def test_gaap_taxonomy_view_get_best_label_returns_none_when_missing() -> None:
    """get_best_label should return None when the concept has no labels."""
    linkbases = _build_linkbases_for_labels()
    view = GaapTaxonomyView(linkbases=linkbases)

    assert view.get_best_label("us-gaap:DoesNotExist") is None


def test_gaap_taxonomy_view_build_presentation_tree_roots_and_children() -> None:
    """build_presentation_tree should construct a deterministic tree."""
    linkbases = _build_linkbases_for_presentation()
    view = GaapTaxonomyView(linkbases=linkbases)

    roots = view.build_presentation_tree("role-income-statement")
    assert isinstance(roots, tuple)
    assert roots, "Expected at least one root node in presentation tree."

    # Our synthetic tree has a single root "Revenues".
    root = roots[0]
    assert isinstance(root, PresentationNode)
    assert root.concept_qname == "us-gaap:Revenues"

    # Children should reflect the presentation chain Revenues → OperatingIncomeLoss → NetIncomeLoss
    assert len(root.children) == 1
    operating_node = root.children[0]
    assert operating_node.concept_qname == "us-gaap:OperatingIncomeLoss"

    assert len(operating_node.children) == 1
    net_income_node = operating_node.children[0]
    assert net_income_node.concept_qname == "us-gaap:NetIncomeLoss"

    # No further descendants.
    assert net_income_node.children == ()


def test_gaap_taxonomy_view_build_presentation_tree_empty_for_unknown_role() -> None:
    """Unknown roles should return an empty presentation tree."""
    linkbases = _build_linkbases_for_presentation()
    view = GaapTaxonomyView(linkbases=linkbases)

    roots = view.build_presentation_tree("role-nonexistent")
    assert roots == ()
