# src/arche_api/application/use_cases/external_apis/edgar/ingest_edgar_filing.py
# Copyright (c)
# SPDX-License-Identifier: MIT
"""Use case: Ingest a single EDGAR filing and its statement versions.

Scope:
    * Given a CIK and accession_id:
        - Resolve company identity via EDGAR ingestion gateway.
        - Locate the target filing in EDGAR submissions.
        - Build metadata-only statement versions.
        - Persist filing + statement versions via repositories inside a UoW.
        - Return the number of statement versions persisted.

Notes:
    * This is an application-layer use case that depends on:
        - Domain-facing EDGAR ingestion gateway.
        - Application UnitOfWork abstraction.
    * Concrete repositories live in the adapters layer and are resolved
      indirectly via the UnitOfWork. This module avoids direct imports
      from adapters to preserve clean architecture layering.
"""

from __future__ import annotations

import logging
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import date
from importlib import import_module
from typing import Any

from arche_api.application.uow import UnitOfWork
from arche_api.domain.entities.edgar_company import EdgarCompanyIdentity
from arche_api.domain.entities.edgar_filing import EdgarFiling
from arche_api.domain.enums.edgar import StatementType
from arche_api.domain.exceptions.edgar import EdgarIngestionError, EdgarMappingError
from arche_api.domain.interfaces.gateways.edgar_ingestion_gateway import (
    EdgarIngestionGateway,
)

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class IngestEdgarFilingRequest:
    """Request parameters for EDGAR filing ingest."""

    cik: str
    accession_id: str
    statement_types: Sequence[StatementType]


class IngestEdgarFilingUseCase:
    """Ingest a single EDGAR filing and its statement versions.

    This use case orchestrates fetching a single filing (header plus one or more
    statement versions) from the EDGAR ingestion gateway and persisting it via
    the unit of work.

    Args:
        gateway: EDGAR ingestion gateway used to fetch filing metadata and
            statement payloads.
        uow: Application unit-of-work responsible for persisting filings and
            statement versions.

    Returns:
        int: The number of statement versions that were successfully ingested.

    Raises:
        EdgarIngestionError: If the filing cannot be fetched, is invalid,
            or cannot be persisted.
    """

    def __init__(
        self,
        *,
        gateway: EdgarIngestionGateway,
        uow: UnitOfWork,
    ) -> None:
        """Initialize the use case.

        Args:
            gateway: EDGAR ingestion gateway used to fetch filing and statements.
            uow: Unit-of-work used to manage the ingestion transaction.
        """
        self._gateway = gateway
        self._uow = uow

    async def execute(self, req: IngestEdgarFilingRequest) -> int:
        """Execute ingest of the specified filing.

        Returns:
            Number of statement versions persisted.
        """
        cik = req.cik.strip()
        accession_id = req.accession_id.strip()

        if not cik:
            raise EdgarMappingError("CIK must not be empty for filing ingest.")
        if not accession_id:
            raise EdgarMappingError("accession_id must not be empty for filing ingest.")

        logger.info(
            "edgar.ingest_filing.start",
            extra={
                "cik": cik,
                "accession_id": accession_id,
                "statement_types": [st.value for st in req.statement_types],
            },
        )

        company = await self._gateway.fetch_company_identity(cik)
        self._ensure_company_identity_matches(company, cik)

        filing = await self._locate_filing(company=company, accession_id=accession_id)

        statement_types = list(req.statement_types) or list(StatementType)

        versions = await self._gateway.fetch_statement_versions_for_filing(
            filing=filing,
            statement_types=statement_types,
        )

        async with self._uow as tx:
            filings_repo = _get_edgar_filings_repository(tx)
            statements_repo = _get_edgar_statements_repository(tx)

            await filings_repo.upsert_filings([filing])
            if versions:
                await statements_repo.upsert_statement_versions(versions)

            await tx.commit()

        logger.info(
            "edgar.ingest_filing.success",
            extra={
                "cik": cik,
                "accession_id": accession_id,
                "statement_versions_count": len(versions),
            },
        )

        return len(versions)

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _ensure_company_identity_matches(
        company: EdgarCompanyIdentity,
        expected_cik: str,
    ) -> None:
        if company.cik != expected_cik:
            raise EdgarIngestionError(
                "EDGAR company identity CIK mismatch for ingest_edgar_filing.",
                details={"requested_cik": expected_cik, "resolved_cik": company.cik},
            )

    async def _locate_filing(
        self,
        *,
        company: EdgarCompanyIdentity,
        accession_id: str,
    ) -> EdgarFiling:
        """Locate a specific filing for a company via the ingestion gateway."""
        today = date.today()
        min_date = date(1994, 1, 1)

        filings = await self._gateway.fetch_filings_for_company(
            company=company,
            filing_types=(),
            from_date=min_date,
            to_date=today,
            include_amendments=True,
            max_results=None,
        )

        for filing in filings:
            if filing.accession_id == accession_id:
                return filing

        logger.warning(
            "edgar.ingest_filing.not_found",
            extra={
                "cik": company.cik,
                "accession_id": accession_id,
                "scanned_filings": len(filings),
            },
        )
        raise EdgarIngestionError(
            "Requested EDGAR filing not found in EDGAR submissions.",
            details={"cik": company.cik, "accession_id": accession_id},
        )


def _get_edgar_filings_repository(tx: Any) -> Any:
    """Resolve the EDGAR filings repository via the UnitOfWork.

    Test doubles may expose `filings_repo` instead of a full registry.
    """
    if hasattr(tx, "filings_repo"):
        return tx.filings_repo

    module = import_module("arche_api.adapters.repositories.edgar_filings_repository")
    repo_cls = module.EdgarFilingsRepository
    return tx.get_repository(repo_cls)


def _get_edgar_statements_repository(tx: Any) -> Any:
    """Resolve the EDGAR statements repository via the UnitOfWork.

    Test doubles may expose `statements_repo` instead of a full registry.
    """
    if hasattr(tx, "statements_repo"):
        return tx.statements_repo

    module = import_module("arche_api.adapters.repositories.edgar_statements_repository")
    repo_cls = module.EdgarStatementsRepository
    return tx.get_repository(repo_cls)
