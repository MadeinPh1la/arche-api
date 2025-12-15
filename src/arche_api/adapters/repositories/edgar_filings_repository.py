# src/arche_api/adapters/repositories/edgar_filings_repository.py
# Copyright (c)
# SPDX-License-Identifier: MIT
"""EDGAR filings repository (SQLAlchemy).

Purpose:
    Provide persistence and query primitives for EDGAR filings backed by the
    ``sec.filings`` table. This repository is responsible for:

      * Idempotent upsert by accession (natural key).
      * Resolving reference-company IDs from CIKs.
      * Deterministic query patterns by CIK, form type, and date windows.
      * Domain-friendly retrieval helpers that map ORM rows to entities.

Design:
    - Accessions are treated as globally unique and enforced via a unique
      constraint in the database.
    - Upsert is implemented via PostgreSQL ``ON CONFLICT`` on ``accession``,
      with last-write-wins semantics for non-key fields.
    - Company foreign keys are resolved via ``ref.companies.cik``; if a
      mapping is missing, the filing is still stored with a NULL company_id
      but a non-null CIK.

Layer:
    adapters / repositories

Notes:
    - Callers in the domain/application layers should work with domain
      entities (EdgarFiling / EdgarCompanyIdentity), not ORM models.
"""

from __future__ import annotations

import time
from collections.abc import Mapping, Sequence
from contextlib import suppress
from datetime import UTC, date, datetime
from datetime import time as dtime
from typing import Any
from uuid import UUID, uuid5

from sqlalchemy import Select, and_, select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession

from arche_api.adapters.repositories.base_repository import BaseRepository
from arche_api.domain.entities.edgar_company import EdgarCompanyIdentity
from arche_api.domain.entities.edgar_filing import EdgarFiling
from arche_api.domain.enums.edgar import FilingType
from arche_api.domain.exceptions.edgar import EdgarMappingError
from arche_api.infrastructure.database.models.ref import Company
from arche_api.infrastructure.database.models.sec import Filing
from arche_api.infrastructure.observability.metrics import (
    get_db_errors_total,
    get_db_operation_duration_seconds,
)

# Stable namespace for deterministic UUID generation from accessions.
_EDGAR_FILING_NAMESPACE = UUID("00000000-0000-0000-0000-000000000001")


class EdgarFilingsRepository(BaseRepository[Filing]):
    """Repository for EDGAR filings persisted in ``sec.filings``.

    This repository provides idempotent upsert behavior keyed by accession and
    deterministic query patterns for downstream financial modeling use cases.
    """

    _MODEL_NAME = "sec_filings"

    def __init__(self, session: AsyncSession) -> None:
        """Initialize the repository.

        Args:
            session: Async SQLAlchemy session bound to the primary database.
        """
        super().__init__(session=session)
        self._metrics_hist = get_db_operation_duration_seconds()
        self._metrics_err = get_db_errors_total()

    # ----------------------------------------------------------------------
    # Public UPSERT API
    # ----------------------------------------------------------------------

    async def upsert_filing(self, filing: EdgarFiling) -> None:
        """Convenience wrapper to upsert a single filing entity.

        This matches the singular-style repository API used in tests and
        higher-level ingestion flows, while delegating to the batch
        implementation for actual persistence.
        """
        await self.upsert_filings([filing])

    async def upsert_filings(
        self,
        filings: Sequence[EdgarFiling],
        *,
        company_overrides: Mapping[str, UUID] | None = None,
    ) -> int:
        """Upsert a batch of EDGAR filings by accession.

        Behavior:
            * Accessions are treated as the natural key and enforced via a
              unique constraint.
            * Last-write-wins semantics for non-key fields.
            * Attempts to resolve ``company_id`` from ``ref.companies.cik``.
              When not found and not overridden, filings are stored with
              ``company_id = NULL`` but a non-null CIK.

        Args:
            filings: Sequence of domain filing entities to persist.
            company_overrides: Optional mapping from CIK → company_id. This
                can be used by higher-level ingest flows that have already
                performed company resolution.

        Returns:
            Number of input filings processed (len(filings)).

        Raises:
            EdgarMappingError: If a filing has an invalid or empty accession.
        """
        if not filings:
            return 0

        start = time.perf_counter()
        outcome = "success"

        try:
            # Deduplicate by accession: last-write-wins on input side.
            dedup: dict[str, EdgarFiling] = {}
            for filing in filings:
                acc = filing.accession_id.strip()
                if not acc:
                    raise EdgarMappingError("accession_id must not be empty.")
                dedup[acc] = filing

            cik_to_company_id = await self._resolve_company_ids(
                cik_list={f.company.cik for f in dedup.values()},
                overrides=company_overrides or {},
            )

            payload: list[dict[str, Any]] = []
            for acc, filing in dedup.items():
                company = filing.company
                company_id = cik_to_company_id.get(company.cik)

                filed_at_dt = datetime.combine(
                    filing.filing_date,
                    dtime.min,
                    tzinfo=UTC,
                )

                # Stable deterministic UUID for idempotency.
                filing_uuid = uuid5(_EDGAR_FILING_NAMESPACE, acc)

                payload.append(
                    {
                        "filing_id": filing_uuid,
                        "company_id": company_id,
                        "cik": company.cik,
                        "accession": filing.accession_id,
                        "form_type": filing.filing_type.value,
                        "filed_at": filed_at_dt,
                        "period_of_report": filing.period_end_date,
                        # We intentionally do not set metadata yet; it remains NULL.
                        "is_amendment": filing.is_amendment,
                        "amendment_sequence": filing.amendment_sequence,
                        "primary_document": filing.primary_document,
                        "accepted_at": filing.accepted_at,
                        "filing_url": None,
                        "data_source": filing.data_source,
                    }
                )

            stmt = pg_insert(Filing).values(payload)
            stmt = stmt.on_conflict_do_update(
                index_elements=[Filing.accession],
                set_={
                    "company_id": stmt.excluded.company_id,
                    "cik": stmt.excluded.cik,
                    "form_type": stmt.excluded.form_type,
                    "filed_at": stmt.excluded.filed_at,
                    "period_of_report": stmt.excluded.period_of_report,
                    # We skip metadata updates for now.
                    "is_amendment": stmt.excluded.is_amendment,
                    "amendment_sequence": stmt.excluded.amendment_sequence,
                    "primary_document": stmt.excluded.primary_document,
                    "accepted_at": stmt.excluded.accepted_at,
                    "filing_url": stmt.excluded.filing_url,
                    "data_source": stmt.excluded.data_source,
                },
            )

            await self._session.execute(stmt)
            return len(filings)

        except Exception as exc:  # noqa: BLE001
            outcome = "error"
            with suppress(Exception):
                self._metrics_err.labels(
                    operation="upsert_filings",
                    model=self._MODEL_NAME,
                    reason=type(exc).__name__,
                ).inc()
            raise

        finally:
            with suppress(Exception):
                duration = time.perf_counter() - start
                self._metrics_hist.labels(
                    operation="upsert_filings",
                    model=self._MODEL_NAME,
                    outcome=outcome,
                ).observe(duration)

    # ----------------------------------------------------------------------
    # Domain-friendly QUERIES
    # ----------------------------------------------------------------------

    async def get_filing_by_accession(self, accession_id: str) -> EdgarFiling | None:
        """Return a domain `EdgarFiling` by accession, if present.

        Args:
            accession_id: Normalized EDGAR accession identifier.

        Returns:
            A mapped `EdgarFiling` instance or ``None`` if not found.

        Raises:
            EdgarMappingError: If the accession_id is empty/blank.
        """
        if not accession_id.strip():
            raise EdgarMappingError("accession_id must not be empty for lookup.")

        stmt: Select[Any] = (
            select(Filing, Company)
            .join(Company, Filing.company_id == Company.company_id, isouter=True)
            .where(Filing.accession == accession_id)
            .order_by(Filing.filing_id.asc())
            .limit(1)
        )
        res = await self._session.execute(stmt)
        row = res.first()
        if row is None:
            return None

        filing_row, company_row = row
        return self._map_to_domain_filing(
            filing_row=filing_row,
            company_row=company_row,
        )

    async def get_by_accession(self, accession: str) -> Filing | None:
        """Low-level ORM helper retained for compatibility.

        Prefer `get_filing_by_accession` in new code.
        """
        if not accession.strip():
            raise EdgarMappingError("accession must not be empty for lookup.")

        stmt: Select[Any] = select(Filing).where(Filing.accession == accession)
        stmt = self.order_by_pk(stmt, Filing.filing_id, ascending=True).limit(1)
        return await self.fetch_optional(stmt)

    async def list_filings_for_company(
        self,
        company: EdgarCompanyIdentity,
        *,
        from_date: date | None = None,
        to_date: date | None = None,
        filing_types: Sequence[FilingType] | None = None,
        limit: int | None = None,
    ) -> list[Filing]:
        """List filings for a company CIK with optional filters.

        Args:
            company: Company identity used for filtering by CIK.
            from_date: Inclusive lower bound on filing date (date-only).
            to_date: Inclusive upper bound on filing date (date-only).
            filing_types: Optional sequence of filing types to include.
            limit: Optional maximum number of rows to return.

        Returns:
            List of ORM Filing instances ordered by:

                filed_at DESC NULLS LAST, filing_id ASC
        """
        conditions: list[Any] = [Filing.cik == company.cik]

        if from_date is not None:
            from_dt = datetime.combine(from_date, dtime.min, tzinfo=UTC)
            conditions.append(Filing.filed_at >= from_dt)
        if to_date is not None:
            to_dt = datetime.combine(to_date, dtime.max, tzinfo=UTC)
            conditions.append(Filing.filed_at <= to_dt)

        if filing_types:
            type_values = [ft.value for ft in filing_types]
            conditions.append(Filing.form_type.in_(type_values))

        stmt: Select[Any] = select(Filing).where(and_(*conditions))
        stmt = self.order_by_latest(stmt, Filing.filed_at, Filing.filing_id)
        if limit is not None and limit > 0:
            stmt = stmt.limit(limit)

        return await self.fetch_all(stmt)

    # ----------------------------------------------------------------------
    # Internal helpers
    # ----------------------------------------------------------------------

    async def _resolve_company_ids(
        self,
        *,
        cik_list: set[str],
        overrides: Mapping[str, UUID],
    ) -> dict[str, UUID]:
        """Resolve CIK → company_id via overrides and ref.companies.

        Args:
            cik_list: Set of CIKs to resolve.
            overrides: Pre-resolved CIK → company_id mapping.

        Returns:
            Mapping of CIK → company_id for all CIKs that could be resolved.
            CIKs that cannot be resolved are simply omitted from the result.
        """
        resolved: dict[str, UUID] = {}

        # Apply overrides first.
        for cik, company_id in overrides.items():
            if cik in cik_list:
                resolved[cik] = company_id

        remaining = [c for c in cik_list if c not in resolved]
        if not remaining:
            return resolved

        stmt = select(Company.cik, Company.company_id).where(Company.cik.in_(remaining))
        res = await self._session.execute(stmt)
        for cik, company_id in res.all():
            resolved[str(cik)] = company_id

        return resolved

    @staticmethod
    def _map_to_domain_filing(
        *,
        filing_row: Filing,
        company_row: Company | None,
    ) -> EdgarFiling:
        """Map ORM rows into a domain `EdgarFiling`.

        This uses the ref.companies row when available to populate a rich
        `EdgarCompanyIdentity`; otherwise it falls back to CIK-only identity.
        """
        if company_row is not None and company_row.cik is not None:
            company_identity = EdgarCompanyIdentity(
                cik=company_row.cik,
                ticker=None,
                legal_name=company_row.name,
                exchange=None,
                country=None,
            )
        else:
            company_identity = EdgarCompanyIdentity(
                cik=filing_row.cik,
                ticker=None,
                legal_name=company_row.name if company_row is not None else filing_row.cik,
                exchange=None,
                country=None,
            )

        filing_type = FilingType(filing_row.form_type)
        filing_date = filing_row.filed_at.date()

        return EdgarFiling(
            accession_id=filing_row.accession,
            company=company_identity,
            filing_type=filing_type,
            filing_date=filing_date,
            period_end_date=filing_row.period_of_report,
            accepted_at=filing_row.accepted_at,
            is_amendment=filing_row.is_amendment,
            amendment_sequence=filing_row.amendment_sequence,
            primary_document=filing_row.primary_document,
            data_source=filing_row.data_source,
        )
