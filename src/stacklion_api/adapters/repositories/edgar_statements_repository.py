# src/stacklion_api/adapters/repositories/edgar_statements_repository.py
# Copyright (c)
# SPDX-License-Identifier: MIT
"""EDGAR statement versions repository (SQLAlchemy)."""

from __future__ import annotations

import time
from collections.abc import Sequence
from contextlib import suppress
from typing import Any, cast
from uuid import uuid4

from sqlalchemy import Select, insert, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import aliased

from stacklion_api.adapters.repositories.base_repository import BaseRepository
from stacklion_api.domain.entities.edgar_company import EdgarCompanyIdentity
from stacklion_api.domain.entities.edgar_filing import EdgarFiling
from stacklion_api.domain.entities.edgar_statement_version import EdgarStatementVersion
from stacklion_api.domain.enums.edgar import (
    AccountingStandard,
    FilingType,
    FiscalPeriod,
    StatementType,
)
from stacklion_api.domain.exceptions.edgar import EdgarIngestionError
from stacklion_api.infrastructure.database.models.ref import Company
from stacklion_api.infrastructure.database.models.sec import Filing, StatementVersion
from stacklion_api.infrastructure.observability.metrics import (
    get_db_errors_total,
    get_db_operation_duration_seconds,
)


class EdgarStatementsRepository(BaseRepository[StatementVersion]):
    """SQLAlchemy-backed EDGAR statements repository."""

    _MODEL_NAME = "sec_statement_versions"

    def __init__(self, session: AsyncSession) -> None:
        super().__init__(session=session)
        self._metrics_hist = get_db_operation_duration_seconds()
        self._metrics_err = get_db_errors_total()

    # ------------------------------------------------------------------
    # UPSERT
    # ------------------------------------------------------------------

    async def upsert_statement_version(
        self,
        version: EdgarStatementVersion,
    ) -> None:
        """Insert a single statement version."""
        await self.upsert_statement_versions([version])

    async def upsert_statement_versions(
        self,
        versions: Sequence[EdgarStatementVersion],
    ) -> None:
        """Insert a batch of statement versions."""
        if not versions:
            return

        start = time.perf_counter()
        outcome = "success"

        try:
            cik_set = {v.company.cik for v in versions}
            cik_to_company = await self._fetch_companies_by_cik(cik_set)

            accession_set = {v.accession_id for v in versions}
            accession_to_filing = await self._fetch_filings_by_accession(accession_set)

            payload: list[dict[str, Any]] = []
            for v in versions:
                company = cik_to_company.get(v.company.cik)
                if company is None:
                    raise EdgarIngestionError(
                        "No ref.company found for EDGAR statement version.",
                        details={"cik": v.company.cik},
                    )

                filing = accession_to_filing.get(v.accession_id)
                if filing is None:
                    raise EdgarIngestionError(
                        "No sec.filings row found for EDGAR statement version.",
                        details={"accession_id": v.accession_id},
                    )

                payload.append(
                    {
                        "statement_version_id": uuid4(),
                        "company_id": company.company_id,
                        "filing_id": filing.filing_id,
                        "statement_type": v.statement_type.value,
                        "accounting_standard": v.accounting_standard.value,
                        "statement_date": v.statement_date,
                        "fiscal_year": v.fiscal_year,
                        "fiscal_period": v.fiscal_period.value,
                        "currency": v.currency,
                        "is_restated": v.is_restated,
                        "restatement_reason": v.restatement_reason,
                        "version_source": v.version_source,
                        "version_sequence": v.version_sequence,
                        "accession_id": v.accession_id,
                        "filing_date": v.filing_date,
                    }
                )

            stmt = insert(StatementVersion).values(payload)
            await self._session.execute(stmt)

        except Exception as exc:  # noqa: BLE001
            outcome = "error"
            with suppress(Exception):
                self._metrics_err.labels(
                    operation="upsert_statement_versions",
                    model=self._MODEL_NAME,
                    reason=type(exc).__name__,
                ).inc()
            raise

        finally:
            with suppress(Exception):
                duration = time.perf_counter() - start
                self._metrics_hist.labels(
                    operation="upsert_statement_versions",
                    model=self._MODEL_NAME,
                    outcome=outcome,
                ).observe(duration)

    # ------------------------------------------------------------------
    # QUERIES
    # ------------------------------------------------------------------

    async def latest_statement_version_for_company(
        self,
        *,
        cik: str,
        statement_type: StatementType,
        fiscal_year: int,
        fiscal_period: FiscalPeriod,
    ) -> EdgarStatementVersion | None:
        """Return the latest statement version for a company/year/period."""
        start = time.perf_counter()
        outcome = "success"

        try:
            company = await self._get_company_by_cik(cik)
            if company is None:
                return None

            sv = aliased(StatementVersion)
            f = aliased(Filing)

            stmt: Select[Any] = (
                select(sv, f)
                .join(f, sv.filing_id == f.filing_id)
                .where(
                    sv.company_id == company.company_id,
                    sv.statement_type == statement_type.value,
                    sv.fiscal_year == fiscal_year,
                    sv.fiscal_period == fiscal_period.value,
                )
                .order_by(sv.version_sequence.desc(), sv.statement_version_id.asc())
                .limit(1)
            )

            res = await self._session.execute(stmt)
            row = res.first()
            if row is None:
                return None

            sv_row, filing_row = cast(tuple[StatementVersion, Filing], row)
            return self._map_to_domain(company, filing_row, sv_row)

        except Exception as exc:  # noqa: BLE001
            outcome = "error"
            with suppress(Exception):
                self._metrics_err.labels(
                    operation="latest_statement_version_for_company",
                    model=self._MODEL_NAME,
                    reason=type(exc).__name__,
                ).inc()
            raise

        finally:
            with suppress(Exception):
                duration = time.perf_counter() - start
                self._metrics_hist.labels(
                    operation="latest_statement_version_for_company",
                    model=self._MODEL_NAME,
                    outcome=outcome,
                ).observe(duration)

    async def list_statement_versions_for_company(
        self,
        *,
        cik: str,
        statement_type: StatementType,
        fiscal_year: int,
        fiscal_period: FiscalPeriod | None = None,
    ) -> list[EdgarStatementVersion]:
        """List all statement versions for a company/year/type (optionally period)."""
        start = time.perf_counter()
        outcome = "success"

        try:
            company = await self._get_company_by_cik(cik)
            if company is None:
                return []

            sv = aliased(StatementVersion)
            f = aliased(Filing)

            conditions: list[Any] = [
                sv.company_id == company.company_id,
                sv.statement_type == statement_type.value,
                sv.fiscal_year == fiscal_year,
            ]
            if fiscal_period is not None:
                conditions.append(sv.fiscal_period == fiscal_period.value)

            stmt: Select[Any] = (
                select(sv, f)
                .join(f, sv.filing_id == f.filing_id)
                .where(*conditions)
                .order_by(sv.version_sequence.asc(), sv.statement_version_id.asc())
            )

            res = await self._session.execute(stmt)
            rows = cast(list[tuple[StatementVersion, Filing]], res.all())
            return [self._map_to_domain(company, filing_row, sv_row) for sv_row, filing_row in rows]

        except Exception as exc:  # noqa: BLE001
            outcome = "error"
            with suppress(Exception):
                self._metrics_err.labels(
                    operation="list_statement_versions_for_company",
                    model=self._MODEL_NAME,
                    reason=type(exc).__name__,
                ).inc()
            raise

        finally:
            with suppress(Exception):
                duration = time.perf_counter() - start
                self._metrics_hist.labels(
                    operation="list_statement_versions_for_company",
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
        if not ciks:
            return {}

        stmt = select(Company).where(Company.cik.in_(list(ciks)))
        res = await self._session.execute(stmt)
        rows: list[Company] = list(res.scalars().all())
        return {row.cik: row for row in rows if row.cik is not None}

    async def _fetch_filings_by_accession(
        self,
        accessions: set[str],
    ) -> dict[str, Filing]:
        if not accessions:
            return {}

        stmt = select(Filing).where(Filing.accession.in_(list(accessions)))
        res = await self._session.execute(stmt)
        rows: list[Filing] = list(res.scalars().all())
        return {row.accession: row for row in rows}

    async def _get_company_by_cik(self, cik: str) -> Company | None:
        stmt = select(Company).where(Company.cik == cik).limit(1)
        res = await self._session.execute(stmt)
        return res.scalar_one_or_none()

    @staticmethod
    def _map_to_domain(
        company_row: Company,
        filing_row: Filing,
        sv_row: StatementVersion,
    ) -> EdgarStatementVersion:
        """Map ORM rows into a domain `EdgarStatementVersion`."""
        if company_row.cik is None:
            raise EdgarIngestionError(
                "ref.company has null CIK; cannot map to EdgarCompanyIdentity.",
                details={"company_id": str(company_row.company_id)},
            )

        company_identity = EdgarCompanyIdentity(
            cik=company_row.cik,
            ticker=None,
            legal_name=company_row.name,
            exchange=None,
            country=None,
        )

        filing_type = FilingType(filing_row.form_type)
        filing = EdgarFiling(
            accession_id=filing_row.accession,
            company=company_identity,
            filing_type=filing_type,
            filing_date=sv_row.filing_date,
            period_end_date=filing_row.period_of_report,
            accepted_at=filing_row.accepted_at,
            is_amendment=filing_row.is_amendment,
            amendment_sequence=filing_row.amendment_sequence,
            primary_document=filing_row.primary_document,
            data_source=filing_row.data_source,
        )

        statement_type = StatementType(sv_row.statement_type)
        accounting_standard = AccountingStandard(sv_row.accounting_standard)
        fiscal_period = FiscalPeriod(sv_row.fiscal_period)

        return EdgarStatementVersion(
            company=company_identity,
            filing=filing,
            statement_type=statement_type,
            accounting_standard=accounting_standard,
            statement_date=sv_row.statement_date,
            fiscal_year=sv_row.fiscal_year,
            fiscal_period=fiscal_period,
            currency=sv_row.currency,
            is_restated=sv_row.is_restated,
            restatement_reason=sv_row.restatement_reason,
            version_source=sv_row.version_source,
            version_sequence=sv_row.version_sequence,
            accession_id=sv_row.accession_id,
            filing_date=sv_row.filing_date,
        )
