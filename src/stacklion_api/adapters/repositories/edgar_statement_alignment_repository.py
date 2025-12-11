# src/stacklion_api/adapters/repositories/edgar_statement_alignment_repository.py
# Copyright (c)
# SPDX-License-Identifier: MIT
"""EDGAR statement alignment repository (SQLAlchemy).

Purpose:
    Provide persistence and query operations for statement-level alignment
    records in `sec.edgar_statement_alignment`, including deterministic
    timelines for issuers and statements.

Layer:
    adapters/repositories

Design:
    * Uses SQLAlchemy ORM with AsyncSession.
    * Emits Prometheus-style metrics for latency and failures.
    * Maps stitching/alignment outputs into the alignment table shape.
"""

from __future__ import annotations

import time
from collections.abc import Sequence
from contextlib import suppress
from typing import Any, cast
from uuid import uuid4

from sqlalchemy import Select, insert, select, tuple_, update
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import aliased

from stacklion_api.adapters.repositories.base_repository import BaseRepository
from stacklion_api.domain.entities.edgar_dq import NormalizedStatementIdentity
from stacklion_api.domain.enums.edgar import StatementType
from stacklion_api.domain.exceptions.edgar import EdgarIngestionError
from stacklion_api.domain.interfaces.repositories.edgar_statement_alignment_repository import (
    EdgarStatementAlignmentRepository as EdgarStatementAlignmentRepositoryPort,
)
from stacklion_api.domain.interfaces.repositories.edgar_statement_alignment_repository import (
    StatementAlignmentRecord,
)
from stacklion_api.infrastructure.database.models.ref import Company
from stacklion_api.infrastructure.database.models.sec import (
    EdgarStatementAlignment,
    StatementVersion,
)
from stacklion_api.infrastructure.observability.metrics import (
    get_db_errors_total,
    get_db_operation_duration_seconds,
)


class SqlAlchemyEdgarStatementAlignmentRepository(
    BaseRepository[EdgarStatementAlignment],
    EdgarStatementAlignmentRepositoryPort,
):
    """SQLAlchemy-backed EDGAR statement alignment repository."""

    _MODEL_NAME = "sec_edgar_statement_alignment"

    def __init__(self, session: AsyncSession) -> None:
        """Initialize the repository.

        Args:
            session: Async SQLAlchemy session bound to the database.
        """
        super().__init__(session=session)
        self._metrics_hist = get_db_operation_duration_seconds()
        self._metrics_err = get_db_errors_total()

    # ------------------------------------------------------------------
    # UPSERT
    # ------------------------------------------------------------------

    async def upsert_alignments(
        self,
        alignments: Sequence[StatementAlignmentRecord],
    ) -> None:
        """Insert or update a batch of alignment records.

        Semantics:
            - Identity is keyed by `statement_version_id`.
            - If an alignment row already exists for the version, it is
              updated in place; otherwise a new row is inserted.
        """
        if not alignments:
            return

        start = time.perf_counter()
        outcome = "success"

        try:
            # Resolve company + statement_version FKs from the identity fields.
            cik_set = {a.cik for a in alignments}
            cik_to_company = await self._fetch_companies_by_cik(cik_set)

            stmt_versions = await self._fetch_statement_versions(alignments)

            payload: list[dict[str, Any]] = []
            for alignment in alignments:
                company = cik_to_company.get(alignment.cik)
                if company is None:
                    raise EdgarIngestionError(
                        "No ref.company found for EDGAR statement alignment.",
                        details={"cik": alignment.cik},
                    )

                sv = stmt_versions.get(
                    (
                        company.company_id,
                        alignment.statement_type.value,
                        alignment.fiscal_year,
                        alignment.fiscal_period,
                        alignment.version_sequence,
                    ),
                )
                if sv is None:
                    raise EdgarIngestionError(
                        "No sec.statement_versions row found for EDGAR statement alignment.",
                        details={
                            "cik": alignment.cik,
                            "statement_type": alignment.statement_type.value,
                            "fiscal_year": alignment.fiscal_year,
                            "fiscal_period": alignment.fiscal_period,
                            "version_sequence": alignment.version_sequence,
                        },
                    )

                row = {
                    "alignment_id": uuid4(),
                    "statement_version_id": sv.statement_version_id,
                    "company_id": company.company_id,
                    "cik": alignment.cik,
                    "statement_type": alignment.statement_type.value,
                    "fiscal_year": alignment.fiscal_year,
                    "fiscal_period": alignment.fiscal_period,
                    "statement_date": alignment.statement_date,
                    "version_sequence": alignment.version_sequence,
                    "fye_date": getattr(alignment, "fye_date", None),
                    "is_53_week_year": getattr(alignment, "is_53_week_year", False),
                    "period_start": getattr(alignment, "period_start", None),
                    "period_end": getattr(alignment, "period_end", None),
                    "alignment_status": getattr(alignment, "alignment_status", "UNKNOWN"),
                    "is_partial_period": getattr(alignment, "is_partial_period", False),
                    "is_off_cycle_period": getattr(alignment, "is_off_cycle_period", False),
                    "is_irregular_calendar": getattr(
                        alignment,
                        "is_irregular_calendar",
                        False,
                    ),
                    "details": getattr(alignment, "details", None),
                }
                payload.append(row)

            # Simple pattern: try update first, then insert missing.
            for row in payload:
                update_stmt = (
                    update(EdgarStatementAlignment)
                    .where(
                        EdgarStatementAlignment.statement_version_id == row["statement_version_id"],
                    )
                    .values({k: v for k, v in row.items() if k != "alignment_id"})
                )
                result: Any = await self._session.execute(update_stmt)
                affected = getattr(result, "rowcount", None)
                if affected == 0:
                    insert_stmt = insert(EdgarStatementAlignment).values(row)
                    await self._session.execute(insert_stmt)

        except Exception as exc:  # noqa: BLE001
            outcome = "error"
            with suppress(Exception):
                self._metrics_err.labels(
                    operation="upsert_alignments",
                    model=self._MODEL_NAME,
                    reason=type(exc).__name__,
                ).inc()
            raise
        finally:
            with suppress(Exception):
                duration = time.perf_counter() - start
                self._metrics_hist.labels(
                    operation="upsert_alignments",
                    model=self._MODEL_NAME,
                    outcome=outcome,
                ).observe(duration)

    async def upsert_alignment(self, alignment: StatementAlignmentRecord) -> None:
        """Insert or update a single alignment record."""
        await self.upsert_alignments([alignment])

    # ------------------------------------------------------------------
    # QUERIES
    # ------------------------------------------------------------------

    async def get_alignment_for_statement(
        self,
        identity: NormalizedStatementIdentity,
        statement_type: StatementType,
    ) -> StatementAlignmentRecord | None:
        """Return the alignment record for a given normalized statement identity."""
        start = time.perf_counter()
        outcome = "success"

        try:
            company = await self._get_company_by_cik(identity.cik)
            if company is None:
                return None

            sv = aliased(StatementVersion)
            ea = aliased(EdgarStatementAlignment)

            stmt: Select[Any] = (
                select(ea)
                .join(
                    sv,
                    ea.statement_version_id == sv.statement_version_id,
                )
                .where(
                    ea.company_id == company.company_id,
                    ea.cik == identity.cik,
                    ea.statement_type == statement_type.value,
                    ea.fiscal_year == identity.fiscal_year,
                    ea.fiscal_period == identity.fiscal_period.value,
                )
                .order_by(
                    ea.version_sequence.desc(),
                    ea.alignment_id.asc(),
                )
                .limit(1)
            )

            res = await self._session.execute(stmt)
            return res.scalar_one_or_none()

        except Exception as exc:  # noqa: BLE001
            outcome = "error"
            with suppress(Exception):
                self._metrics_err.labels(
                    operation="get_alignment_for_statement",
                    model=self._MODEL_NAME,
                    reason=type(exc).__name__,
                ).inc()
            raise
        finally:
            with suppress(Exception):
                duration = time.perf_counter() - start
                self._metrics_hist.labels(
                    operation="get_alignment_for_statement",
                    model=self._MODEL_NAME,
                    outcome=outcome,
                ).observe(duration)

    async def list_alignment_timeline_for_company(
        self,
        *,
        cik: str,
        statement_type: StatementType | None = None,
    ) -> Sequence[StatementAlignmentRecord]:
        """List alignment records for a company in deterministic timeline order."""
        start = time.perf_counter()
        outcome = "success"

        try:
            company = await self._get_company_by_cik(cik)
            if company is None:
                return []

            ea = aliased(EdgarStatementAlignment)

            conditions: list[Any] = [ea.company_id == company.company_id, ea.cik == cik]
            if statement_type is not None:
                conditions.append(ea.statement_type == statement_type.value)

            stmt: Select[Any] = (
                select(ea)
                .where(*conditions)
                .order_by(
                    ea.fiscal_year.asc(),
                    ea.fiscal_period.asc(),
                    ea.version_sequence.asc(),
                    ea.alignment_id.asc(),
                )
            )

            res = await self._session.execute(stmt)
            rows = list(res.scalars().all())
            # EdgarStatementAlignment satisfies StatementAlignmentRecord,
            # so we cast for type-checking purposes.
            return cast(Sequence[StatementAlignmentRecord], rows)

        except Exception as exc:  # noqa: BLE001
            outcome = "error"
            with suppress(Exception):
                self._metrics_err.labels(
                    operation="list_alignment_timeline_for_company",
                    model=self._MODEL_NAME,
                    reason=type(exc).__name__,
                ).inc()
            raise
        finally:
            with suppress(Exception):
                duration = time.perf_counter() - start
                self._metrics_hist.labels(
                    operation="list_alignment_timeline_for_company",
                    model=self._MODEL_NAME,
                    outcome=outcome,
                ).observe(duration)

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    async def _fetch_companies_by_cik(
        self,
        ciks: set[str],
    ) -> dict[str, Company]:
        """Fetch reference companies by CIK into a lookup map."""
        if not ciks:
            return {}

        stmt = select(Company).where(Company.cik.in_(list(ciks)))
        res = await self._session.execute(stmt)
        rows: list[Company] = list(res.scalars().all())
        return {row.cik: row for row in rows if row.cik is not None}

    async def _fetch_statement_versions(
        self,
        alignments: Sequence[StatementAlignmentRecord],
    ) -> dict[tuple[Any, ...], StatementVersion]:
        """Fetch statement_versions needed for the batch into a lookup map."""
        if not alignments:
            return {}

        company_ciks = {a.cik for a in alignments}
        companies = await self._fetch_companies_by_cik(company_ciks)
        keys: set[tuple[Any, ...]] = set()

        for a in alignments:
            company = companies.get(a.cik)
            if company is None:
                continue
            keys.add(
                (
                    company.company_id,
                    a.statement_type.value,
                    a.fiscal_year,
                    a.fiscal_period,
                    a.version_sequence,
                ),
            )

        if not keys:
            return {}

        sv = aliased(StatementVersion)
        stmt = select(sv).where(
            tuple_(
                sv.company_id,
                sv.statement_type,
                sv.fiscal_year,
                sv.fiscal_period,
                sv.version_sequence,
            ).in_(list(keys)),
        )

        res = await self._session.execute(stmt)
        rows: list[StatementVersion] = list(res.scalars().all())
        return {
            (
                row.company_id,
                row.statement_type,
                row.fiscal_year,
                row.fiscal_period,
                row.version_sequence,
            ): row
            for row in rows
        }

    async def _get_company_by_cik(self, cik: str) -> Company | None:
        """Return the `Company` row for a given CIK, or None if missing."""
        stmt = select(Company).where(Company.cik == cik).limit(1)
        res = await self._session.execute(stmt)
        return res.scalar_one_or_none()
