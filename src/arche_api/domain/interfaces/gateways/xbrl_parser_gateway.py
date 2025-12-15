# src/arche_api/domain/interfaces/gateways/xbrl_parser_gateway.py
# Copyright (c)
# SPDX-License-Identifier: MIT
"""XBRL parser gateway interface.

Purpose:
    Define a domain-level gateway abstraction for parsing raw XBRL or Inline
    XBRL content into :class:`XBRLDocument` value objects. Implementations live
    in the adapters layer.

Layer:
    domain/interfaces/gateways
"""

from __future__ import annotations

from typing import Protocol

from arche_api.domain.entities.xbrl_document import XBRLDocument


class XBRLParserGateway(Protocol):
    """Protocol for adapters that parse raw XBRL into XBRLDocument objects."""

    async def parse_xbrl(
        self,
        *,
        accession_id: str,
        content: bytes | str,
    ) -> XBRLDocument:
        """Parse raw XBRL content into an :class:`XBRLDocument`.

        Args:
            accession_id:
                EDGAR accession identifier associated with the XBRL document.
            content:
                Raw XBRL or Inline XBRL content (bytes or string).

        Returns:
            Parsed :class:`XBRLDocument` instance.
        """
