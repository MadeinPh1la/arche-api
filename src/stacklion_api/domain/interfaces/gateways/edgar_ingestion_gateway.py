# src/stacklion_api/domain/interfaces/gateways/edgar_ingestion_gateway.py
# Copyright (c) Stacklion.
# SPDX-License-Identifier: MIT
"""
EDGAR ingestion gateway interface.

Purpose:
- Define a provider-agnostic interface for fetching and normalizing EDGAR filings
  and financial statement versions from external transports (EDGAR APIs, mirrors).
- Hide transport, pagination, and rate-limiting concerns behind a stable domain
  contract.

Layer: domain

Notes:
- Implementations live in the adapters/infrastructure layers (e.g., HTTP clients,
  batch ingestors) and must translate transport errors into domain exceptions.
"""

from __future__ import annotations

from collections.abc import Sequence
from datetime import date
from typing import Protocol

from stacklion_api.domain.entities.edgar_company import EdgarCompanyIdentity
from stacklion_api.domain.entities.edgar_filing import EdgarFiling
from stacklion_api.domain.entities.edgar_statement_version import EdgarStatementVersion
from stacklion_api.domain.enums.edgar import FilingType, StatementType


class EdgarIngestionGateway(Protocol):
    """Protocol for EDGAR ingestion gateways.

    Implementations are responsible for:
      - Fetching raw EDGAR data via HTTP, S3, etc.
      - Validating and mapping it into domain entities.
      - Translating transport/validation errors into domain exceptions.

    All methods must be deterministic for identical inputs and must not leak
    transport-specific details into the domain layer.
    """

    async def fetch_company_identity(self, cik: str) -> EdgarCompanyIdentity:
        """Fetch and normalize the company identity for a given CIK.

        Args:
            cik: Central Index Key assigned by the SEC.

        Returns:
            Normalized company identity for the filer.

        Raises:
            EdgarNotFound: If the CIK does not correspond to a known filer.
            EdgarIngestionError: On transport or upstream failures.
            EdgarMappingError: If the upstream payload cannot be mapped safely.
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
            company: Company identity for which to fetch filings.
            filing_types: Filing types to include (e.g., 10-K, 10-Q).
            from_date: Inclusive start date for filing_date.
            to_date: Inclusive end date for filing_date.
            include_amendments: Whether to include amendment filings.
            max_results: Optional cap on number of filings to return. Implementations
                must document deterministic ordering (e.g., filing_date desc, then
                accession_id asc).

        Returns:
            A sequence of normalized filing entities.

        Raises:
            EdgarIngestionError: On transport or upstream failures.
            EdgarMappingError: If responses cannot be mapped safely.
        """

    async def fetch_statement_versions_for_filing(
        self,
        filing: EdgarFiling,
        statement_types: Sequence[StatementType],
    ) -> Sequence[EdgarStatementVersion]:
        """Fetch and normalize financial statement versions for a given filing.

        Args:
            filing: Filing for which to retrieve statement versions.
            statement_types: Statement types to include (income, balance sheet,
                cash flow).

        Returns:
            A sequence of statement version entities associated with the filing.

        Raises:
            EdgarIngestionError: On transport or upstream failures.
            EdgarMappingError: If responses cannot be mapped safely.
        """
