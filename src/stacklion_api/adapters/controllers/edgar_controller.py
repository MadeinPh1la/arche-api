# Copyright (c) Stacklion.
# SPDX-License-Identifier: MIT
"""EDGAR Controller.

Summary:
    Thin adapter coordinating EDGAR read-side use cases. Controllers do not
    access repositories or gateways directly; they delegate to use-cases and
    return DTOs suitable for presenters.

Design:
    * Protocol-based use-case interfaces to avoid tight coupling.
    * Simple parameter translation and validation at the controller boundary.
    * No transport concerns; HTTP-specific behavior lives in routers/presenters.

Layer:
    adapters/controllers
"""

from __future__ import annotations

from collections.abc import Sequence
from datetime import date
from typing import Protocol

from stacklion_api.adapters.controllers.base import BaseController
from stacklion_api.application.schemas.dto.edgar import (
    EdgarFilingDTO,
    EdgarStatementVersionDTO,
)
from stacklion_api.domain.enums.edgar import FilingType, StatementType


class ListFilingsUseCase(Protocol):
    """Protocol for a use-case listing filings for a company."""

    async def execute(
        self,
        *,
        cik: str,
        filing_types: Sequence[FilingType] | None,
        from_date: date | None,
        to_date: date | None,
        include_amendments: bool,
        page: int,
        page_size: int,
    ) -> tuple[list[EdgarFilingDTO], int]:
        """Execute the list-filings use case.

        Args:
            cik: Company CIK string, typically a zero-padded identifier.
            filing_types: Optional filter for specific filing types.
            from_date: Optional lower bound on filing date (inclusive).
            to_date: Optional upper bound on filing date (inclusive).
            include_amendments: Whether to include amended filings.
            page: 1-based page index for pagination.
            page_size: Number of items per page.

        Returns:
            A tuple of (filings, total_count) for the given criteria.
        """
        ...


class GetFilingUseCase(Protocol):
    """Protocol for a use-case retrieving a single filing."""

    async def execute(
        self,
        *,
        cik: str,
        accession_id: str,
    ) -> EdgarFilingDTO:
        """Execute the get-filing use case.

        Args:
            cik: Company CIK string.
            accession_id: Filing accession identifier.

        Returns:
            The matching filing DTO.

        Raises:
            Domain-level exceptions if the filing cannot be resolved.
        """
        ...


class ListStatementVersionsUseCase(Protocol):
    """Protocol for a use-case listing statement versions for a company."""

    async def execute(
        self,
        *,
        cik: str,
        statement_type: StatementType,
        from_date: date | None,
        to_date: date | None,
        include_restated: bool,
        page: int,
        page_size: int,
    ) -> tuple[list[EdgarStatementVersionDTO], int]:
        """Execute the list-statement-versions use case.

        Args:
            cik: Company CIK string.
            statement_type: Type of financial statement to filter on.
            from_date: Optional lower bound on statement_date (inclusive).
            to_date: Optional upper bound on statement_date (inclusive).
            include_restated: Whether restated versions should be included.
            page: 1-based page index.
            page_size: Number of items per page.

        Returns:
            A tuple of (statement_versions, total_count).
        """
        ...


class GetStatementVersionsForFilingUseCase(Protocol):
    """Protocol for a use-case retrieving statement versions for a filing."""

    async def execute(
        self,
        *,
        cik: str,
        accession_id: str,
        statement_type: StatementType | None,
        include_restated: bool,
        include_normalized: bool,
    ) -> tuple[EdgarFilingDTO, list[EdgarStatementVersionDTO]]:
        """Execute the get-statement-versions-for-filing use case.

        Args:
            cik: Company CIK string.
            accession_id: Filing accession identifier.
            statement_type: Optional filter for statement type.
            include_restated: Whether to include restated statement versions.
            include_normalized: Whether normalized payloads should be requested.

        Returns:
            A tuple of (filing_dto, statement_versions) for the filing.
        """
        ...


class EdgarController(BaseController):
    """Controller orchestrating EDGAR filings and statement versions."""

    def __init__(
        self,
        list_filings_uc: ListFilingsUseCase,
        get_filing_uc: GetFilingUseCase,
        list_statements_uc: ListStatementVersionsUseCase,
        get_filing_statements_uc: GetStatementVersionsForFilingUseCase,
    ) -> None:
        """Initialize the controller with its use-cases.

        Args:
            list_filings_uc: Use-case responsible for listing filings.
            get_filing_uc: Use-case responsible for retrieving a single filing.
            list_statements_uc: Use-case listing statement versions.
            get_filing_statements_uc: Use-case retrieving versions for a filing.
        """
        self._list_filings_uc = list_filings_uc
        self._get_filing_uc = get_filing_uc
        self._list_statements_uc = list_statements_uc
        self._get_filing_statements_uc = get_filing_statements_uc

    async def list_filings(
        self,
        *,
        cik: str,
        filing_types: Sequence[FilingType] | None,
        from_date: date | None,
        to_date: date | None,
        include_amendments: bool,
        page: int,
        page_size: int,
    ) -> tuple[list[EdgarFilingDTO], int]:
        """List filings for a company.

        Args:
            cik: Company CIK.
            filing_types: Optional filter for filing types.
            from_date: Optional lower bound on filing date (inclusive).
            to_date: Optional upper bound on filing date (inclusive).
            include_amendments: Whether to include amendments.
            page: 1-based page index.
            page_size: Items per page.

        Returns:
            Tuple of (filings, total_count).
        """
        return await self._list_filings_uc.execute(
            cik=cik.strip(),
            filing_types=filing_types,
            from_date=from_date,
            to_date=to_date,
            include_amendments=include_amendments,
            page=page,
            page_size=page_size,
        )

    async def get_filing(
        self,
        *,
        cik: str,
        accession_id: str,
    ) -> EdgarFilingDTO:
        """Retrieve a single filing for a company.

        Args:
            cik: Company CIK.
            accession_id: Filing accession identifier.

        Returns:
            Filing DTO.

        Raises:
            Domain-specific exceptions if the filing does not exist or cannot
            be resolved; routers map these to HTTP errors.
        """
        return await self._get_filing_uc.execute(
            cik=cik.strip(),
            accession_id=accession_id.strip(),
        )

    async def list_statements(
        self,
        *,
        cik: str,
        statement_type: StatementType,
        from_date: date | None,
        to_date: date | None,
        include_restated: bool,
        page: int,
        page_size: int,
    ) -> tuple[list[EdgarStatementVersionDTO], int]:
        """List statement versions for a company.

        Args:
            cik: Company CIK.
            statement_type: Statement type filter (e.g., income statement).
            from_date: Optional lower bound on statement_date (inclusive).
            to_date: Optional upper bound on statement_date (inclusive).
            include_restated: Whether to include restated versions.
            page: 1-based page index.
            page_size: Items per page.

        Returns:
            Tuple of (statement_versions, total_count).
        """
        return await self._list_statements_uc.execute(
            cik=cik.strip(),
            statement_type=statement_type,
            from_date=from_date,
            to_date=to_date,
            include_restated=include_restated,
            page=page,
            page_size=page_size,
        )

    async def get_statement_versions_for_filing(
        self,
        *,
        cik: str,
        accession_id: str,
        statement_type: StatementType | None,
        include_restated: bool,
        include_normalized: bool,
    ) -> tuple[EdgarFilingDTO, list[EdgarStatementVersionDTO]]:
        """Retrieve statement versions associated with a specific filing.

        Args:
            cik: Company CIK.
            accession_id: Filing accession identifier.
            statement_type: Optional filter for statement type.
            include_restated: Whether to include restated versions.
            include_normalized: Whether normalized payloads were requested.

        Returns:
            Tuple of (filing_dto, statement_versions).

        Notes:
            Normalized payloads are not yet populated in E5. The use-case may
            ignore ``include_normalized`` for now while still accepting it.
        """
        return await self._get_filing_statements_uc.execute(
            cik=cik.strip(),
            accession_id=accession_id.strip(),
            statement_type=statement_type,
            include_restated=include_restated,
            include_normalized=include_normalized,
        )
