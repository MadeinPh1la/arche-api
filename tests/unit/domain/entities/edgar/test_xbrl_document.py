# tests/unit/domain/entities/test_xbrl_document.py
# Copyright (c)
# SPDX-License-Identifier: MIT

from __future__ import annotations

from datetime import date
from decimal import Decimal

from stacklion_api.domain.entities.xbrl_document import (
    XBRLContext,
    XBRLDimension,
    XBRLDocument,
    XBRLFact,
    XBRLPeriod,
    XBRLUnit,
)


def test_xbrl_fact_to_decimal_plain() -> None:
    fact = XBRLFact(
        id="f1",
        concept_qname="us-gaap:Revenues",
        context_ref="c1",
        unit_ref="u1",
        raw_value="123.45",
        decimals=None,
        precision=None,
        is_nil=False,
        footnote_refs=(),
    )

    value = fact.to_decimal()
    assert isinstance(value, Decimal)
    assert value == Decimal("123.45")


def test_xbrl_fact_to_decimal_with_decimals_quantizes() -> None:
    fact = XBRLFact(
        id="f2",
        concept_qname="us-gaap:Revenues",
        context_ref="c1",
        unit_ref="u1",
        raw_value="123.4567",
        decimals=2,
        precision=None,
        is_nil=False,
        footnote_refs=(),
    )

    value = fact.to_decimal()
    assert value == Decimal("123.46")


def test_xbrl_fact_to_decimal_nil_returns_none() -> None:
    fact = XBRLFact(
        id="f3",
        concept_qname="us-gaap:Revenues",
        context_ref="c1",
        unit_ref="u1",
        raw_value="9999",
        decimals=0,
        precision=None,
        is_nil=True,
        footnote_refs=(),
    )

    value = fact.to_decimal()
    assert value is None


def test_xbrl_document_round_trip_types() -> None:
    period = XBRLPeriod(
        is_instant=True,
        instant_date=date(2024, 12, 31),
        start_date=None,
        end_date=None,
    )
    ctx = XBRLContext(
        id="C1",
        entity_identifier="0000123456",
        period=period,
        dimensions=(XBRLDimension(dimension_qname="d1", member_qname="m1"),),
    )
    unit = XBRLUnit(id="U1", measure="iso4217:USD")
    fact = XBRLFact(
        id="f1",
        concept_qname="us-gaap:Revenues",
        context_ref="C1",
        unit_ref="U1",
        raw_value="100",
        decimals=0,
        precision=None,
        is_nil=False,
        footnote_refs=("fn1",),
    )

    doc = XBRLDocument(
        accession_id="0000000000-24-000001",
        contexts={"C1": ctx},
        units={"U1": unit},
        facts=(fact,),
    )

    assert doc.accession_id == "0000000000-24-000001"
    assert "C1" in doc.contexts
    assert "U1" in doc.units
    assert len(doc.facts) == 1
