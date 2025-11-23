# src/stacklion_api/domain/interfaces/repositories/edgar_statements_repository.py
# Copyright (c) Stacklion.
# SPDX-License-Identifier: MIT
"""
EDGAR statements repository interface.

Purpose:
    Define persistence and query operations for normalized EDGAR statement
    versions and enforce deterministic access patterns required for financial
    modeling.

Layer:
    domain

Notes:
    Implementations live in the adapters/infrastructure layers (e.g., SQLAlchemy
    repositories) and must translate DB/driver errors into domain exceptions.
    Statement row-level data will be introduced in subsequent phases; this
    repository focuses on statement version metadata.
"""

from __future__ import annotations

from collections.abc import Sequence
from datetime import date
from typing import Protocol

from stacklion_api.domain.entities.edgar_company import EdgarCompanyIdentity
from stacklion_api.domain.entities.edgar_statement_version import EdgarStatementVersion
from stacklion_api.domain.enums.edgar import StatementType


class EdgarStatementsRepository(Protocol):
    """Protocol for repositories managing EDGAR statement versions."""

    async def upsert_statement_versions(
        self,
        versions: Sequence[EdgarStatementVersion],
    ) -> None:
        """Insert or update statement versions in an idempotent manner.

        Implementations must:
            - Treat (company, statement_type, statement_date, version_sequence)
              as a stable identity tuple.
            - Preserve historical versions; never overwrite prior versions in
              place.
            - Ensure deterministic ordering for subsequent queries.

        Args:
            versions: Statement version entities to persist.

        Raises:
            EdgarIngestionError: If persistence fails due to infrastructure
                issues.
        """

    async def get_latest_statement_version(
        self,
        company: EdgarCompanyIdentity,
        statement_type: StatementType,
        statement_date: date,
    ) -> EdgarStatementVersion:
        """Retrieve the latest statement version for a given company and period.

        Args:
            company: Company identity.
            statement_type: Statement type (income, balance sheet, etc.).
            statement_date: Reporting period end date.

        Returns:
            The latest statement version for the specified company and period.

        Raises:
            EdgarNotFound: If no statement version exists for the given inputs.
        """

    async def list_statement_versions(
        self,
        company: EdgarCompanyIdentity,
        statement_type: StatementType,
        from_date: date,
        to_date: date,
        include_restated: bool = False,
    ) -> Sequence[EdgarStatementVersion]:
        """List statement versions for a company and type over a date range.

        Args:
            company: Company identity.
            statement_type: Statement type to filter by.
            from_date: Inclusive lower bound on statement_date.
            to_date: Inclusive upper bound on statement_date.
            include_restated: Whether to include restated versions (True) or only
                the latest non-restated versions per period (False).

        Returns:
            A sequence of statement versions. Implementations must document and
            guarantee deterministic ordering, for example:
                - statement_date asc
                - version_sequence asc
        """
