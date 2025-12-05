# src/stacklion_api/application/use_cases/external_apis/edgar/parse_xbrl_file.py
# SPDX-License-Identifier: MIT
"""Use case: Parse raw XBRL into an XBRLDocument.

Layer:
    application/use_cases/external_apis/edgar

Purpose:
    Accept raw XBRL bytes from the ingestion pipeline and parse them via the
    :class:`XBRLParserGateway` into a pure-domain :class:`XBRLDocument`.
"""

from __future__ import annotations

from dataclasses import dataclass

from stacklion_api.domain.entities.xbrl_document import XBRLDocument
from stacklion_api.domain.interfaces.gateways.xbrl_parser_gateway import (
    XBRLParserGateway,
)


@dataclass(frozen=True)
class ParseXBRLFileRequest:
    """Request parameters for parsing a single XBRL document.

    Attributes:
        cik:
            Company CIK for which the filing belongs. Used for logging and
            traceability only.
        accession_id:
            EDGAR accession identifier for the XBRL instance to parse.
        content:
            Raw XBRL or Inline XBRL content as bytes or string.
    """

    cik: str
    accession_id: str
    content: bytes | str


@dataclass(frozen=True)
class ParseXBRLFileResult:
    """Result of parsing a single XBRL document.

    Attributes:
        document:
            Parsed :class:`XBRLDocument` containing contexts, units, and facts.
    """

    document: XBRLDocument


class ParseXBRLFileUseCase:
    """Use case: parse a single XBRL file via the parser gateway.

    This use case is intentionally thin: it delegates parsing to the
    :class:`XBRLParserGateway` and provides a stable application-layer
    contract for higher-level ingestion workflows.

    Args:
        parser:
            Gateway responsible for turning raw XBRL bytes into an
            :class:`XBRLDocument` instance.
    """

    def __init__(self, parser: XBRLParserGateway) -> None:
        """Initialize the use case.

        Args:
            parser:
                Gateway used to perform XBRL parsing.
        """
        self._parser = parser

    async def execute(self, req: ParseXBRLFileRequest) -> ParseXBRLFileResult:
        """Execute XBRL parsing for the requested filing.

        Args:
            req:
                Request parameters identifying the target XBRL instance and
                providing its raw content.

        Returns:
            A :class:`ParseXBRLFileResult` containing the parsed document.
        """
        document = await self._parser.parse_xbrl(
            accession_id=req.accession_id,
            content=req.content,
        )
        return ParseXBRLFileResult(document=document)
