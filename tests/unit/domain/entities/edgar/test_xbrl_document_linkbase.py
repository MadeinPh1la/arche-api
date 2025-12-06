# tests/unit/domain/entities/test_xbrl_document_linkbase.py
# Copyright (c)
# SPDX-License-Identifier: MIT
"""Tests for XBRL linkbase domain entities."""

from __future__ import annotations

import math

import pytest

from stacklion_api.domain.entities.xbrl_document import (
    XBRLLabel,
    XBRLLinkbaseNetworks,
    XBRLPresentationArc,
)


def test_xbrl_label_requires_non_empty_fields() -> None:
    """XBRLLabel should enforce non-empty concept_qname, role, and text."""
    label = XBRLLabel(
        concept_qname="us-gaap:Revenues",
        role="http://www.xbrl.org/2003/role/label",
        text="Revenues",
    )

    assert label.concept_qname == "us-gaap:Revenues"
    assert label.role.endswith("/label")
    assert label.text == "Revenues"

    with pytest.raises(ValueError):
        XBRLLabel(concept_qname="", role="role", text="x")  # type: ignore[arg-type]

    with pytest.raises(ValueError):
        XBRLLabel(concept_qname="us-gaap:Revenues", role="", text="x")

    with pytest.raises(ValueError):
        XBRLLabel(concept_qname="us-gaap:Revenues", role="role", text="")


def test_xbrl_presentation_arc_validates_non_empty_and_finite_order() -> None:
    """XBRLPresentationArc should enforce non-empty fields and finite order."""
    arc = XBRLPresentationArc(
        role="role-income-statement",
        parent_qname="us-gaap:Revenues",
        child_qname="us-gaap:NetIncomeLoss",
        order=10.0,
    )

    assert arc.role == "role-income-statement"
    assert arc.parent_qname == "us-gaap:Revenues"
    assert arc.child_qname == "us-gaap:NetIncomeLoss"
    assert arc.order == 10.0

    # Empty fields should fail.
    with pytest.raises(ValueError):
        XBRLPresentationArc(
            role="",
            parent_qname="us-gaap:Revenues",
            child_qname="us-gaap:NetIncomeLoss",
            order=1.0,
        )

    with pytest.raises(ValueError):
        XBRLPresentationArc(
            role="role-income-statement",
            parent_qname="",
            child_qname="us-gaap:NetIncomeLoss",
            order=1.0,
        )

    with pytest.raises(ValueError):
        XBRLPresentationArc(
            role="role-income-statement",
            parent_qname="us-gaap:Revenues",
            child_qname="",
            order=1.0,
        )

    # Non-finite order should fail.
    with pytest.raises(ValueError):
        XBRLPresentationArc(
            role="role-income-statement",
            parent_qname="us-gaap:Revenues",
            child_qname="us-gaap:NetIncomeLoss",
            order=math.nan,
        )

    with pytest.raises(ValueError):
        XBRLPresentationArc(
            role="role-income-statement",
            parent_qname="us-gaap:Revenues",
            child_qname="us-gaap:NetIncomeLoss",
            order=math.inf,
        )


def test_xbrl_linkbase_networks_accepts_mappings_and_sequences() -> None:
    """XBRLLinkbaseNetworks should preserve labels mapping and arcs tuple."""
    label = XBRLLabel(
        concept_qname="us-gaap:Revenues",
        role="http://www.xbrl.org/2003/role/label",
        text="Revenues",
    )
    arc = XBRLPresentationArc(
        role="role-income-statement",
        parent_qname="us-gaap:Revenues",
        child_qname="us-gaap:NetIncomeLoss",
        order=1.0,
    )

    networks = XBRLLinkbaseNetworks(
        labels_by_concept={"us-gaap:Revenues": (label,)},
        presentation_arcs=(arc,),
    )

    assert "us-gaap:Revenues" in networks.labels_by_concept
    assert networks.labels_by_concept["us-gaap:Revenues"][0].text == "Revenues"
    assert len(networks.presentation_arcs) == 1
    assert networks.presentation_arcs[0].child_qname == "us-gaap:NetIncomeLoss"
