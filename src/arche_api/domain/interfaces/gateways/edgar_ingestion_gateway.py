# src/arche_api/domain/interfaces/gateways/edgar_ingestion_gateway.py
# Copyright (c)
# SPDX-License-Identifier: MIT
"""Domain-level EDGAR ingestion gateway protocol.

Purpose:
    Define the contract that application use-cases rely on for EDGAR data:

        * Company identity lookup.
        * Filing metadata retrieval.
        * Construction of metadata-only statement versions.
        * XBRL instance retrieval.
        * Optional fact-level (provider-specific) access.

Implementations:
    Concrete implementations live in the adapters layer, for example
    :class:`arche_api.adapters.gateways.edgar_gateway.HttpEdgarIngestionGateway`.

Layer:
    domain/interfaces/gateways
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from datetime import date
from typing import Protocol

from arche_api.domain.entities.edgar_company import EdgarCompanyIdentity
from arche_api.domain.entities.edgar_filing import EdgarFiling
from arche_api.domain.entities.edgar_statement_version import EdgarStatementVersion
from arche_api.domain.enums.edgar import FilingType, StatementType
from arche_api.domain.services.edgar_normalization import EdgarFact


class EdgarIngestionGateway(Protocol):
    """Protocol for EDGAR ingestion providers.

    Implementations are responsible for translating upstream EDGAR payloads
    (JSON / HTML / XBRL) into domain entities and value objects.

    Methods are intentionally high-level and tailored to application
    use-cases rather than raw HTTP endpoints.
    """

    async def fetch_company_identity(self, cik: str) -> EdgarCompanyIdentity:
        """Fetch and normalize the company identity for a given CIK.

        Args:
            cik:
                Central Index Key for the filer. May contain non-digit
                characters; implementations are expected to normalize it.

        Returns:
            An :class:`EdgarCompanyIdentity` describing the filer.
        """

    async def fetch_recent_filings(self, *, cik: str, limit: int = 100) -> Mapping[str, object]:
        """Fetch the raw recent-filings JSON payload for a company.

        This is primarily used by staging/ingest UCs that work against the
        submissions JSON structure.

        Args:
            cik:
                Central Index Key for the filer (pre-normalization).
            limit:
                Optional upper bound on the number of filings to return in the
                normalized payload.

        Returns:
            A mapping representing the normalized "recent filings" payload.
        """

    async def fetch_filings_for_company(
        self,
        company: EdgarCompanyIdentity,
        filing_types: Sequence[FilingType],
        from_date: date,
        to_date: date,
        include_amendments: bool = True,
        max_results: int | None = None,
    ) -> Sequence[EdgarFiling]:
        """Fetch filings for a company within a date range.

        Args:
            company:
                Company identity for which to fetch filings.
            filing_types:
                Filing types to include (e.g., 10-K, 10-Q). An empty sequence
                means "all supported types."
            from_date:
                Inclusive lower bound on ``filing_date``.
            to_date:
                Inclusive upper bound on ``filing_date``.
            include_amendments:
                Whether to include amendment forms (e.g., 10-K/A).
            max_results:
                Optional upper bound on the number of filings to return.

        Returns:
            A sequence of :class:`EdgarFiling` entities, typically sorted in
            descending order by (filing_date, accession_id).
        """

    async def fetch_statement_versions_for_filing(
        self,
        filing: EdgarFiling,
        statement_types: Sequence[StatementType],
    ) -> Sequence[EdgarStatementVersion]:
        """Construct metadata-only statement versions for a filing.

        Implementations should not inspect XBRL facts here; the intent is to
        build "skeleton" statement versions that can later be enriched by the
        XBRL normalization pipeline.

        Args:
            filing:
                Filing metadata entity.
            statement_types:
                Statement types to construct versions for. An empty sequence
                should typically result in an empty list.

        Returns:
            A sequence of :class:`EdgarStatementVersion` entities with
            metadata filled and ``normalized_payload`` set to ``None``.
        """

    async def fetch_xbrl_for_filing(self, *, cik: str, accession_id: str) -> bytes:
        """Fetch primary XBRL or Inline XBRL instance bytes for a filing.

        Args:
            cik:
                Central Index Key for the filer.
            accession_id:
                EDGAR accession identifier for the filing (e.g.,
                "0000320193-24-000010").

        Returns:
            Raw XBRL or Inline XBRL document bytes suitable for parsing.

        Raises:
            EdgarIngestionError:
                Implementations should surface transport- or EDGAR-specific
                failures as domain-level ingestion errors.
        """

    async def fetch_facts_for_filing(self, accession_id: str) -> Sequence[EdgarFact]:
        """Fetch provider-specific fact records for a filing.

        This is an optional hook for legacy or alternate fact-level ingestion
        approaches. In the EDGAR XBRL normalization path, applications should
        prefer :meth:`fetch_xbrl_for_filing` + the XBRL parser gateway.

        Args:
            accession_id:
                EDGAR accession identifier for the filing.

        Returns:
            A sequence of :class:`EdgarFact` records describing raw,
            provider-specific facts for the filing.
        """
