# src/stacklion_api/application/use_cases/external_apis/edgar/sync_recent_filings.py
# Copyright (c)
# SPDX-License-Identifier: MIT
"""Use case: Sync recent EDGAR filings for a company.

Scope:
    * For a given CIK:
        - Fetch recent filings from the EDGAR ingestion gateway.
        - Deduplicate against existing `sec.filings` rows.
        - Ingest only new filings and their statement versions.
        - Return the number of statement versions persisted.

Behavior:
    * Idempotent with respect to (company, accession_id).
"""

from __future__ import annotations

import logging
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import date
from importlib import import_module
from typing import Any

from stacklion_api.application.uow import UnitOfWork
from stacklion_api.domain.entities.edgar_company import EdgarCompanyIdentity
from stacklion_api.domain.entities.edgar_filing import EdgarFiling
from stacklion_api.domain.entities.edgar_statement_version import EdgarStatementVersion
from stacklion_api.domain.enums.edgar import FilingType, StatementType
from stacklion_api.domain.exceptions.edgar import EdgarIngestionError, EdgarMappingError
from stacklion_api.domain.interfaces.gateways.edgar_ingestion_gateway import (
    EdgarIngestionGateway,
)

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class SyncRecentFilingsRequest:
    """Request parameters for syncing recent EDGAR filings."""

    cik: str
    filing_types: Sequence[FilingType] | None = None
    from_date: date | None = None
    to_date: date | None = None
    include_amendments: bool = True
    statement_types: Sequence[StatementType] | None = None


class SyncRecentFilingsUseCase:
    """Sync recent EDGAR filings for a company into persistent storage.

    The use case queries the EDGAR gateway for recent filings, filters out
    accessions that already exist in the repository, and ingests only the new
    ones.

    Args:
        gateway: EDGAR ingestion gateway used to discover recent filings and
            drive per-filing ingestion.
        uow: Unit-of-work used to read/write EDGAR filings and statements.

    Returns:
        int: The number of newly ingested statement versions.

    Raises:
        EdgarIngestionError: If the gateway fails or persistence encounters
            an unrecoverable error.
    """

    def __init__(
        self,
        *,
        gateway: EdgarIngestionGateway,
        uow: UnitOfWork,
    ) -> None:
        """Initialize the use case.

        Args:
            gateway: EDGAR ingestion gateway.
            uow: Unit-of-work coordinating repository access.
        """
        self._gateway = gateway
        self._uow = uow

    async def execute(self, req: SyncRecentFilingsRequest) -> int:
        """Execute the sync flow.

        Returns:
            Number of statement versions persisted for newly discovered filings.
        """
        cik = req.cik.strip()
        if not cik:
            raise EdgarMappingError("CIK must not be empty for sync_recent_filings.")

        from_date, to_date = self._normalize_window(req.from_date, req.to_date)

        logger.info(
            "edgar.sync_recent_filings.start",
            extra={
                "cik": cik,
                "from_date": from_date.isoformat(),
                "to_date": to_date.isoformat(),
                "filing_types": [ft.value for ft in (req.filing_types or [])],
                "include_amendments": req.include_amendments,
            },
        )

        company = await self._gateway.fetch_company_identity(cik)
        self._ensure_company_identity_matches(company, cik)

        filing_types = list(req.filing_types or [])

        filings = await self._gateway.fetch_filings_for_company(
            company=company,
            filing_types=filing_types,
            from_date=from_date,
            to_date=to_date,
            include_amendments=req.include_amendments,
            max_results=None,
        )

        if not filings:
            logger.info(
                "edgar.sync_recent_filings.no_candidates",
                extra={"cik": cik},
            )
            return 0

        async with self._uow as tx:
            filings_repo = _get_edgar_filings_repository(tx)
            statements_repo = _get_edgar_statements_repository(tx)

            existing_rows = await filings_repo.list_filings_for_company(
                company=company,
                from_date=from_date,
                to_date=to_date,
                filing_types=filing_types or None,
                limit=None,
            )
            existing_accessions = {row.accession for row in existing_rows}

            new_filings: list[EdgarFiling] = [
                f for f in filings if f.accession_id not in existing_accessions
            ]

            if not new_filings:
                logger.info(
                    "edgar.sync_recent_filings.idempotent",
                    extra={
                        "cik": cik,
                        "from_date": from_date.isoformat(),
                        "to_date": to_date.isoformat(),
                        "existing_count": len(existing_accessions),
                    },
                )
                await tx.commit()
                return 0

            statement_types = list(req.statement_types or []) or list(StatementType)

            all_versions: list[EdgarStatementVersion] = []
            for filing in new_filings:
                versions = await self._gateway.fetch_statement_versions_for_filing(
                    filing=filing,
                    statement_types=statement_types,
                )
                all_versions.extend(versions)

            await filings_repo.upsert_filings(new_filings)
            if all_versions:
                await statements_repo.upsert_statement_versions(all_versions)

            await tx.commit()

        logger.info(
            "edgar.sync_recent_filings.success",
            extra={
                "cik": cik,
                "from_date": from_date.isoformat(),
                "to_date": to_date.isoformat(),
                "new_filings": len(new_filings),
                "new_versions": len(all_versions),
            },
        )

        return len(all_versions)

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _normalize_window(
        from_date: date | None,
        to_date: date | None,
    ) -> tuple[date, date]:
        """Normalize an optional (from_date, to_date) into concrete bounds."""
        today = date.today()
        lower = from_date or date(1994, 1, 1)
        upper = to_date or today

        if lower > upper:
            raise EdgarMappingError(
                "from_date must be on or before to_date for sync_recent_filings.",
                details={"from_date": lower.isoformat(), "to_date": upper.isoformat()},
            )
        return lower, upper

    @staticmethod
    def _ensure_company_identity_matches(
        company: EdgarCompanyIdentity,
        expected_cik: str,
    ) -> None:
        if company.cik != expected_cik:
            raise EdgarIngestionError(
                "EDGAR company identity CIK mismatch for sync_recent_filings.",
                details={"requested_cik": expected_cik, "resolved_cik": company.cik},
            )


def _get_edgar_filings_repository(tx: Any) -> Any:
    """Resolve the EDGAR filings repository via the UnitOfWork.

    Test doubles may expose `filings_repo` instead of a full registry.
    """
    if hasattr(tx, "filings_repo"):
        return tx.filings_repo

    module = import_module("stacklion_api.adapters.repositories.edgar_filings_repository")
    repo_cls = module.EdgarFilingsRepository
    return tx.get_repository(repo_cls)


def _get_edgar_statements_repository(tx: Any) -> Any:
    """Resolve the EDGAR statements repository via the UnitOfWork.

    Test doubles may expose `repo` or `statements_repo` attributes instead of
    a full repository registry. Prefer those when present to keep tests simple.
    """
    if hasattr(tx, "repo"):
        return tx.repo
    if hasattr(tx, "statements_repo"):
        return tx.statements_repo

    module = import_module("stacklion_api.adapters.repositories.edgar_statements_repository")
    repo_cls = module.EdgarStatementsRepository
    return tx.get_repository(repo_cls)
