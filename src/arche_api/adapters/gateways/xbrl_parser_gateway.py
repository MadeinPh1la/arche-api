# src/arche_api/adapters/gateways/xbrl_parser_gateway.py
# Copyright (c)
# SPDX-License-Identifier: MIT
"""XBRL parser gateway adapter.

Purpose:
    Provide an adapter-layer implementation of the XBRLParserGateway protocol
    using the XML-based XBRLParser. This keeps XML parsing details out of the
    application and domain layers.

Layer:
    adapters/gateways
"""

from __future__ import annotations

from arche_api.adapters.mappers.xbrl_parser import XBRLParser
from arche_api.domain.entities.xbrl_document import XBRLDocument
from arche_api.domain.interfaces.gateways.xbrl_parser_gateway import (
    XBRLParserGateway,
)


class DefaultXBRLParserGateway(XBRLParserGateway):
    """Default XBRL parser gateway backed by XBRLParser."""

    def __init__(self) -> None:
        """Initialize the gateway with a concrete XBRLParser."""
        self._parser = XBRLParser()

    async def parse_xbrl(
        self,
        *,
        accession_id: str,
        content: bytes | str,
    ) -> XBRLDocument:
        """Parse raw XBRL content into an XBRLDocument.

        Args:
            accession_id:
                EDGAR accession identifier associated with the document.
            content:
                Raw XBRL or Inline XBRL content.

        Returns:
            Parsed XBRLDocument instance.
        """
        # Parsing is CPU-bound and synchronous in E10-A; the async boundary is
        # at the gateway interface level for consistency with other gateways.
        return self._parser.parse(accession_id=accession_id, content=content)
