# src/arche_api/application/use_cases/statements/get_normalized_statement.py
# Copyright (c)
# SPDX-License-Identifier: MIT
"""Use case: Retrieve the latest normalized EDGAR statement version.

Purpose:
    Provide a deterministic, modeling-ready view of the latest statement
    version for a given (CIK, statement_type, fiscal_year, fiscal_period)
    identity tuple, including its attached canonical normalized payload and
    optional version history.

Layer:
    application

Notes:
    - This use case is read-only and does not perform any writes.
    - It depends on the EDGAR statements repository via the application
      UnitOfWork abstraction.
    - Routers/presenters are responsible for shaping the response into HTTP
      envelopes or MCP payloads.
"""

from __future__ import annotations

import logging
from collections.abc import Sequence
from dataclasses import dataclass
from typing import Any, cast

from arche_api.application.uow import UnitOfWork
from arche_api.domain.entities.edgar_statement_version import EdgarStatementVersion
from arche_api.domain.enums.edgar import FiscalPeriod, StatementType
from arche_api.domain.exceptions.edgar import EdgarIngestionError, EdgarMappingError
from arche_api.domain.interfaces.repositories.edgar_statements_repository import (
    EdgarStatementsRepository as EdgarStatementsRepositoryProtocol,
)

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class GetNormalizedStatementRequest:
    """Request parameters for retrieving a normalized statement.

    Attributes:
        cik: Central Index Key for the filer.
        statement_type: Statement type (income, balance sheet, cash flow, etc.).
        fiscal_year: Fiscal year associated with the statement (must be > 0).
        fiscal_period: Fiscal period within the year (e.g., FY, Q1, Q2).
        include_version_history:
            Whether to return the full list of statement versions for the
            identity tuple alongside the latest version.
    """

    cik: str
    statement_type: StatementType
    fiscal_year: int
    fiscal_period: FiscalPeriod
    include_version_history: bool = True


@dataclass(frozen=True)
class NormalizedStatementResult:
    """Result for the GetNormalizedStatement use case.

    Attributes:
        latest_version:
            Latest :class:`EdgarStatementVersion` for the requested identity
            tuple. The entity must have a non-None ``normalized_payload``.
        version_history:
            All versions of the statement for the same identity tuple,
            ordered by (version_sequence ASC, statement_version_id ASC).
            Empty when ``include_version_history`` was False.
    """

    latest_version: EdgarStatementVersion
    version_history: Sequence[EdgarStatementVersion]


class GetNormalizedStatementUseCase:
    """Fetch the latest normalized statement plus optional version history.

    Args:
        uow: Unit-of-work used to access the EDGAR statements repository.

    Returns:
        GetNormalizedStatementResponse: Object containing the latest normalized
        payload and, optionally, the version history for the requested period.

    Raises:
        EdgarIngestionError: If no versions exist for the requested period or
            the latest version lacks a normalized payload.
    """

    def __init__(self, uow: UnitOfWork) -> None:
        """Initialize the use case.

        Args:
            uow: Application UnitOfWork abstraction used to resolve repositories.
        """
        self._uow = uow

    async def execute(self, req: GetNormalizedStatementRequest) -> NormalizedStatementResult:
        """Execute the normalized statement lookup.

        Args:
            req: Parameters describing the target statement identity.

        Returns:
            A :class:`NormalizedStatementResult` containing the latest statement
            version and, optionally, its version history.

        Raises:
            EdgarMappingError:
                If the request parameters are invalid (e.g., empty CIK,
                non-positive fiscal_year).
            EdgarIngestionError:
                If no statement version exists for the requested identity tuple
                or if the latest version does not have a normalized payload
                attached.
        """
        cik = req.cik.strip()
        if not cik:
            raise EdgarMappingError("CIK must not be empty for get_normalized_statement().")

        if req.fiscal_year <= 0:
            raise EdgarMappingError(
                "fiscal_year must be a positive integer for get_normalized_statement().",
                details={"fiscal_year": req.fiscal_year},
            )

        logger.info(
            "edgar.get_normalized_statement.start",
            extra={
                "cik": cik,
                "statement_type": req.statement_type.value,
                "fiscal_year": req.fiscal_year,
                "fiscal_period": req.fiscal_period.value,
                "include_version_history": req.include_version_history,
            },
        )

        async with self._uow as tx:
            statements_repo = _get_edgar_statements_repository(tx)

            latest = await statements_repo.latest_statement_version_for_company(
                cik=cik,
                statement_type=req.statement_type,
                fiscal_year=req.fiscal_year,
                fiscal_period=req.fiscal_period,
            )

            if latest is None:
                logger.info(
                    "edgar.get_normalized_statement.not_found",
                    extra={
                        "cik": cik,
                        "statement_type": req.statement_type.value,
                        "fiscal_year": req.fiscal_year,
                        "fiscal_period": req.fiscal_period.value,
                    },
                )
                raise EdgarIngestionError(
                    "No EDGAR statement version found for requested identity.",
                    details={
                        "cik": cik,
                        "statement_type": req.statement_type.value,
                        "fiscal_year": req.fiscal_year,
                        "fiscal_period": req.fiscal_period.value,
                    },
                )

            if latest.normalized_payload is None:
                logger.warning(
                    "edgar.get_normalized_statement.no_normalized_payload",
                    extra={
                        "cik": cik,
                        "statement_type": req.statement_type.value,
                        "fiscal_year": req.fiscal_year,
                        "fiscal_period": req.fiscal_period.value,
                        "version_sequence": latest.version_sequence,
                    },
                )
                raise EdgarIngestionError(
                    "Latest EDGAR statement version does not have a normalized payload.",
                    details={
                        "cik": cik,
                        "statement_type": req.statement_type.value,
                        "fiscal_year": req.fiscal_year,
                        "fiscal_period": req.fiscal_period.value,
                        "version_sequence": latest.version_sequence,
                    },
                )

            version_history: Sequence[EdgarStatementVersion] = ()
            if req.include_version_history:
                version_history = await statements_repo.list_statement_versions_for_company(
                    cik=cik,
                    statement_type=req.statement_type,
                    fiscal_year=req.fiscal_year,
                    fiscal_period=req.fiscal_period,
                )

        logger.info(
            "edgar.get_normalized_statement.success",
            extra={
                "cik": cik,
                "statement_type": req.statement_type.value,
                "fiscal_year": req.fiscal_year,
                "fiscal_period": req.fiscal_period.value,
                "version_sequence": latest.version_sequence,
                "history_count": len(version_history),
            },
        )

        return NormalizedStatementResult(
            latest_version=latest,
            version_history=version_history,
        )


def _get_edgar_statements_repository(tx: Any) -> EdgarStatementsRepositoryProtocol:
    """Resolve the EDGAR statements repository via the UnitOfWork.

    Test doubles may expose `repo`, `statements_repo`, or `_repo` attributes
    instead of a full repository registry. Prefer those when present to keep
    tests and fakes simple.
    """
    if hasattr(tx, "repo"):
        return cast(EdgarStatementsRepositoryProtocol, tx.repo)
    if hasattr(tx, "statements_repo"):
        return cast(EdgarStatementsRepositoryProtocol, tx.statements_repo)
    if hasattr(tx, "_repo"):
        return cast(EdgarStatementsRepositoryProtocol, tx._repo)

    return cast(
        EdgarStatementsRepositoryProtocol,
        tx.get_repository(EdgarStatementsRepositoryProtocol),
    )
