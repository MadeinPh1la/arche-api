# src/arche_api/application/interfaces/edgar_gateway.py
# Copyright (c) Arche.
# SPDX-License-Identifier: MIT
"""Application-level EDGAR gateway interface.

Purpose:
    Provide a high-level, use-case-friendly interface for EDGAR ingestion and
    read operations. Allow application use cases to orchestrate filings and
    statement versions without depending directly on low-level transport or
    persistence details.

Layer:
    application

Notes:
    Implementations will typically be thin facades over:
        - domain.interfaces.gateways.Edg arIngestionGateway
        - domain.interfaces.repositories.Edg arStatementsRepository
    This interface is intentionally narrow and focused on the most common
    modeling flows (ingestion + read).
"""

from __future__ import annotations

from collections.abc import Sequence
from datetime import date
from typing import Protocol

from arche_api.domain.entities.edgar_company import EdgarCompanyIdentity
from arche_api.domain.entities.edgar_statement_version import EdgarStatementVersion
from arche_api.domain.enums.edgar import FilingType, StatementType


class EdgarGateway(Protocol):
    """Application-level gateway for EDGAR ingestion and retrieval."""

    async def ingest_filings_and_statements_for_company(
        self,
        cik: str,
        filing_types: Sequence[FilingType],
        from_date: date,
        to_date: date,
        include_amendments: bool = True,
    ) -> Sequence[EdgarStatementVersion]:
        """Ingest filings and statement versions for a company into storage.

        This method is responsible for:
            - Resolving the company identity from the given CIK.
            - Fetching filings and associated statement versions from the
              upstream EDGAR source.
            - Persisting statement versions via the EDGAR statements repository
              using idempotent upsert semantics.
            - Returning the ingested statement versions for further processing.

        Args:
            cik: Central Index Key for the filer.
            filing_types: Filing types to include (e.g., 10-K, 10-Q).
            from_date: Inclusive lower bound on filing_date.
            to_date: Inclusive lower bound on filing_date.
            include_amendments: Whether to include amendment filings.

        Returns:
            A sequence of ingested statement versions.

        Raises:
            EdgarIngestionError: On upstream or persistence failures.
            EdgarMappingError: If upstream payloads cannot be mapped safely.
        """

    async def list_statement_versions_for_company(
        self,
        company: EdgarCompanyIdentity,
        statement_type: StatementType,
        from_date: date,
        to_date: date,
        include_restated: bool = False,
    ) -> Sequence[EdgarStatementVersion]:
        """List statement versions from persistent storage for modeling purposes.

        Args:
            company: Company identity.
            statement_type: Statement type to filter by.
            from_date: Inclusive lower bound on statement_date.
            to_date: Inclusive upper bound on statement_date.
            include_restated: Whether to include restated versions.

        Returns:
            A sequence of stored statement versions.
        """

    async def get_latest_statement_version_for_period(
        self,
        company: EdgarCompanyIdentity,
        statement_type: StatementType,
        statement_date: date,
    ) -> EdgarStatementVersion:
        """Retrieve the latest stored statement version for a given period.

        Args:
            company: Company identity.
            statement_type: Statement type (income, balance sheet, etc.).
            statement_date: Reporting period end date.

        Returns:
            The latest stored statement version for the specified period.

        Raises:
            EdgarNotFound: If no version exists for the specified inputs.
        """
