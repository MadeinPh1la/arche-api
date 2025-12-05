# tests/unit/adapters/mappers/test_xbrl_parser.py
# Copyright (c)
# SPDX-License-Identifier: MIT

from __future__ import annotations

from datetime import date

from stacklion_api.adapters.mappers.xbrl_parser import XBRLParser

_SIMPLE_XBRL = """
<xbrli:xbrl xmlns:xbrli="http://www.xbrl.org/2003/instance"
            xmlns:us-gaap="http://fasb.org/us-gaap/2024">
  <xbrli:context id="C1">
    <xbrli:entity>
      <xbrli:identifier>0000123456</xbrli:identifier>
    </xbrli:entity>
    <xbrli:period>
      <xbrli:instant>2024-12-31</xbrli:instant>
    </xbrli:period>
  </xbrli:context>

  <xbrli:unit id="U1">
    <xbrli:measure>iso4217:USD</xbrli:measure>
  </xbrli:unit>

  <us-gaap:Revenues contextRef="C1" unitRef="U1" decimals="0">100</us-gaap:Revenues>
</xbrli:xbrl>
""".strip()


def test_xbrl_parser_parses_contexts_units_and_facts() -> None:
    parser = XBRLParser()

    doc = parser.parse(accession_id="0000000000-24-000001", content=_SIMPLE_XBRL)

    assert doc.accession_id == "0000000000-24-000001"
    assert "C1" in doc.contexts
    assert "U1" in doc.units
    assert len(doc.facts) == 1

    ctx = doc.contexts["C1"]
    assert ctx.entity_identifier == "0000123456"
    assert ctx.period.is_instant is True
    assert ctx.period.instant_date == date(2024, 12, 31)

    unit = doc.units["U1"]
    assert unit.measure == "iso4217:USD"

    fact = doc.facts[0]
    assert fact.concept_qname == "us-gaap:Revenues"
    assert fact.context_ref == "C1"
    assert fact.unit_ref == "U1"
    assert fact.raw_value == "100"
    assert fact.decimals == 0
