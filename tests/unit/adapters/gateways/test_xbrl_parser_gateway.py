# tests/unit/adapters/gateways/test_xbrl_parser_gateway.py
# Copyright (c)
# SPDX-License-Identifier: MIT

from __future__ import annotations

from arche_api.adapters.gateways.xbrl_parser_gateway import DefaultXBRLParserGateway

_SIMPLE_XBRL = """
<xbrli:xbrl xmlns:xbrli="http://www.xbrl.org/2003/instance">
</xbrli:xbrl>
""".strip()


async def test_default_xbrl_parser_gateway_parses_document() -> None:
    gateway = DefaultXBRLParserGateway()

    doc = await gateway.parse_xbrl(
        accession_id="0000000000-24-000001",
        content=_SIMPLE_XBRL,
    )

    assert doc.accession_id == "0000000000-24-000001"
    # No facts, contexts, or units in this minimal sample.
    assert doc.facts == ()
    assert doc.contexts == {}
    assert doc.units == {}
