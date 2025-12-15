# src/arche_api/adapters/repositories/edgar_reconciliation_checks_repository.py
# Copyright (c)
# SPDX-License-Identifier: MIT
"""EDGAR reconciliation checks repository (SQLAlchemy).

Purpose:
    Provide persistence and query operations for reconciliation rule evaluation
    results in `sec.edgar_reconciliation_checks`, including deterministic reads
    for modeling workloads.

Layer:
    adapters/repositories

Design:
    * Uses SQLAlchemy ORM with AsyncSession.
    * Emits Prometheus-style metrics for latency and failures.
    * Append-only semantics: inserts new ledger entries for each run.
    * Deterministic ordering for statement- and window-scoped queries.
"""

from __future__ import annotations

import time
from collections.abc import Mapping, Sequence
from contextlib import suppress
from datetime import date, datetime
from decimal import Decimal
from typing import Any
from uuid import UUID, uuid4

from sqlalchemy import Select, insert, select, tuple_
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import aliased

from arche_api.adapters.repositories.base_repository import BaseRepository
from arche_api.domain.entities.edgar_dq import NormalizedStatementIdentity
from arche_api.domain.entities.edgar_reconciliation import ReconciliationResult
from arche_api.domain.enums.edgar import FiscalPeriod, MaterialityClass, StatementType
from arche_api.domain.enums.edgar_reconciliation import (
    ReconciliationRuleCategory,
    ReconciliationStatus,
)
from arche_api.domain.exceptions.edgar import EdgarIngestionError
from arche_api.domain.interfaces.repositories.edgar_reconciliation_checks_repository import (
    EdgarReconciliationChecksRepository as EdgarReconciliationChecksRepositoryPort,
)
from arche_api.infrastructure.database.models.ref import Company
from arche_api.infrastructure.database.models.sec import (
    EdgarReconciliationCheck,
    StatementVersion,
)
from arche_api.infrastructure.observability.metrics import (
    get_db_errors_total,
    get_db_operation_duration_seconds,
)


class SqlAlchemyEdgarReconciliationChecksRepository(
    BaseRepository[EdgarReconciliationCheck],
    EdgarReconciliationChecksRepositoryPort,
):
    """SQLAlchemy-backed EDGAR reconciliation checks ledger repository."""

    _MODEL_NAME = "sec_edgar_reconciliation_checks"

    def __init__(self, session: AsyncSession) -> None:
        """Initialize the repository.

        Args:
            session: Async SQLAlchemy session bound to the database.
        """
        super().__init__(session=session)
        self._metrics_hist = get_db_operation_duration_seconds()
        self._metrics_err = get_db_errors_total()

    # ------------------------------------------------------------------
    # APPEND (LEDGER WRITE)
    # ------------------------------------------------------------------

    async def append_results(
        self,
        *,
        reconciliation_run_id: str,
        executed_at: datetime,
        results: Sequence[ReconciliationResult],
    ) -> None:
        """Append reconciliation results to the persistent ledger.

        Semantics:
            - Append-only: each call inserts new ledger rows.
            - Resolves company_id via ref.companies.cik.
            - Resolves statement_version_id via sec.statement_versions identity.

        Args:
            reconciliation_run_id: UUID string for the reconciliation run.
            executed_at: Timestamp at which the run completed.
            results: Results to persist.

        Raises:
            EdgarIngestionError: If required FK rows cannot be resolved.
        """
        if not results:
            return

        start = time.perf_counter()
        outcome = "success"

        try:
            run_uuid = UUID(reconciliation_run_id)

            ciks = {r.statement_identity.cik for r in results}
            cik_to_company = await self._fetch_companies_by_cik(ciks)

            stmt_versions = await self._fetch_statement_versions(
                identities=[r.statement_identity for r in results],
                cik_to_company=cik_to_company,
            )

            payload: list[dict[str, Any]] = []
            for result in results:
                company = cik_to_company.get(result.statement_identity.cik)
                if company is None:
                    raise EdgarIngestionError(
                        "No ref.company found for EDGAR reconciliation check persistence.",
                        details={"cik": result.statement_identity.cik},
                    )

                sv_key = (
                    company.company_id,
                    result.statement_identity.statement_type.value,
                    result.statement_identity.fiscal_year,
                    result.statement_identity.fiscal_period.value,
                    result.statement_identity.version_sequence,
                )
                sv = stmt_versions.get(sv_key)
                if sv is None:
                    raise EdgarIngestionError(
                        "No sec.statement_versions row found for EDGAR reconciliation check persistence.",
                        details={
                            "cik": result.statement_identity.cik,
                            "statement_type": result.statement_identity.statement_type.value,
                            "fiscal_year": result.statement_identity.fiscal_year,
                            "fiscal_period": result.statement_identity.fiscal_period.value,
                            "version_sequence": result.statement_identity.version_sequence,
                        },
                    )

                payload.append(
                    self._to_row_dict(
                        result=result,
                        reconciliation_run_id=run_uuid,
                        executed_at=executed_at,
                        company_id=company.company_id,
                        statement_version_id=sv.statement_version_id,
                        statement_date=sv.statement_date,
                    )
                )

            await self._session.execute(insert(EdgarReconciliationCheck).values(payload))

        except Exception as exc:  # noqa: BLE001
            outcome = "error"
            with suppress(Exception):
                self._metrics_err.labels(
                    operation="append_results",
                    model=self._MODEL_NAME,
                    reason=type(exc).__name__,
                ).inc()
            raise
        finally:
            with suppress(Exception):
                self._metrics_hist.labels(
                    operation="append_results",
                    model=self._MODEL_NAME,
                    outcome=outcome,
                ).observe(time.perf_counter() - start)

    # ------------------------------------------------------------------
    # QUERIES
    # ------------------------------------------------------------------

    async def list_for_statement(
        self,
        *,
        identity: NormalizedStatementIdentity,
        reconciliation_run_id: str | None = None,
        limit: int | None = None,
    ) -> Sequence[ReconciliationResult]:
        """List checks for a statement identity in deterministic order.

        Ordering:
            executed_at ASC,
            rule_category ASC,
            rule_id ASC,
            dimension_key ASC NULLS LAST,
            check_id ASC

        Args:
            identity: Normalized statement identity (including version_sequence).
            reconciliation_run_id: Optional run UUID string to filter results.
            limit: Optional maximum number of rows.

        Returns:
            Deterministically ordered reconciliation results.
        """
        start = time.perf_counter()
        outcome = "success"

        try:
            company = await self._get_company_by_cik(identity.cik)
            if company is None or company.cik is None:
                return []

            rc = aliased(EdgarReconciliationCheck)

            conditions: list[Any] = [
                rc.company_id == company.company_id,
                rc.cik == identity.cik,
                rc.statement_type == identity.statement_type.value,
                rc.fiscal_year == identity.fiscal_year,
                rc.fiscal_period == identity.fiscal_period.value,
                rc.version_sequence == identity.version_sequence,
            ]
            if reconciliation_run_id is not None:
                conditions.append(rc.reconciliation_run_id == UUID(reconciliation_run_id))

            stmt: Select[Any] = (
                select(rc)
                .where(*conditions)
                .order_by(
                    rc.executed_at.asc(),
                    rc.rule_category.asc(),
                    rc.rule_id.asc(),
                    rc.dimension_key.asc().nulls_last(),
                    rc.check_id.asc(),
                )
            )
            if limit is not None:
                stmt = stmt.limit(limit)

            res = await self._session.execute(stmt)
            rows = list(res.scalars().all())
            return [self._map_to_domain(row=row, cik=company.cik) for row in rows]

        except Exception as exc:  # noqa: BLE001
            outcome = "error"
            with suppress(Exception):
                self._metrics_err.labels(
                    operation="list_for_statement",
                    model=self._MODEL_NAME,
                    reason=type(exc).__name__,
                ).inc()
            raise
        finally:
            with suppress(Exception):
                self._metrics_hist.labels(
                    operation="list_for_statement",
                    model=self._MODEL_NAME,
                    outcome=outcome,
                ).observe(time.perf_counter() - start)

    async def list_for_window(
        self,
        *,
        cik: str,
        statement_type: str,
        fiscal_year_from: int,
        fiscal_year_to: int,
        limit: int = 5000,
    ) -> Sequence[ReconciliationResult]:
        """List checks across a fiscal-year window deterministically.

        Ordering:
            fiscal_year ASC,
            fiscal_period ASC,
            version_sequence ASC,
            executed_at ASC,
            rule_category ASC,
            rule_id ASC,
            dimension_key ASC NULLS LAST,
            check_id ASC

        Args:
            cik: Company CIK.
            statement_type: Statement type code (StatementType.value).
            fiscal_year_from: Inclusive start year.
            fiscal_year_to: Inclusive end year.
            limit: Maximum number of rows.

        Returns:
            Deterministically ordered reconciliation results.
        """
        start = time.perf_counter()
        outcome = "success"

        try:
            company = await self._get_company_by_cik(cik)
            if company is None or company.cik is None:
                return []

            rc = aliased(EdgarReconciliationCheck)

            stmt: Select[Any] = (
                select(rc)
                .where(
                    rc.company_id == company.company_id,
                    rc.cik == cik,
                    rc.statement_type == statement_type,
                    rc.fiscal_year >= fiscal_year_from,
                    rc.fiscal_year <= fiscal_year_to,
                )
                .order_by(
                    rc.fiscal_year.asc(),
                    rc.fiscal_period.asc(),
                    rc.version_sequence.asc(),
                    rc.executed_at.asc(),
                    rc.rule_category.asc(),
                    rc.rule_id.asc(),
                    rc.dimension_key.asc().nulls_last(),
                    rc.check_id.asc(),
                )
                .limit(limit)
            )

            res = await self._session.execute(stmt)
            rows = list(res.scalars().all())
            return [self._map_to_domain(row=row, cik=company.cik) for row in rows]

        except Exception as exc:  # noqa: BLE001
            outcome = "error"
            with suppress(Exception):
                self._metrics_err.labels(
                    operation="list_for_window",
                    model=self._MODEL_NAME,
                    reason=type(exc).__name__,
                ).inc()
            raise
        finally:
            with suppress(Exception):
                self._metrics_hist.labels(
                    operation="list_for_window",
                    model=self._MODEL_NAME,
                    outcome=outcome,
                ).observe(time.perf_counter() - start)

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    async def _fetch_companies_by_cik(self, ciks: set[str]) -> dict[str, Company]:
        """Fetch reference companies by CIK into a lookup map."""
        if not ciks:
            return {}

        res = await self._session.execute(select(Company).where(Company.cik.in_(list(ciks))))
        rows: list[Company] = list(res.scalars().all())
        return {row.cik: row for row in rows if row.cik is not None}

    async def _fetch_statement_versions(
        self,
        *,
        identities: Sequence[NormalizedStatementIdentity],
        cik_to_company: Mapping[str, Company],
    ) -> dict[tuple[Any, ...], StatementVersion]:
        """Fetch statement_versions needed for a batch into a lookup map."""
        if not identities:
            return {}

        keys: set[tuple[Any, ...]] = set()
        for identity in identities:
            company = cik_to_company.get(identity.cik)
            if company is None:
                continue
            keys.add(
                (
                    company.company_id,
                    identity.statement_type.value,
                    identity.fiscal_year,
                    identity.fiscal_period.value,
                    identity.version_sequence,
                )
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
            ).in_(list(keys))
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
        res = await self._session.execute(select(Company).where(Company.cik == cik).limit(1))
        return res.scalar_one_or_none()

    @staticmethod
    def _to_row_dict(
        *,
        result: ReconciliationResult,
        reconciliation_run_id: UUID,
        executed_at: datetime,
        company_id: UUID,
        statement_version_id: UUID,
        statement_date: date,
    ) -> dict[str, Any]:
        """Convert a domain reconciliation result into a row dict for insertion.

        Args:
            result: Domain reconciliation result to persist.
            reconciliation_run_id: UUID for the reconciliation run.
            executed_at: Timestamp at which the reconciliation run completed.
            company_id: Resolved ref.companies.company_id.
            statement_version_id: Resolved sec.statement_versions.statement_version_id.
            statement_date: Statement end date from statement_versions.

        Returns:
            Dict suitable for SQLAlchemy insert(values=[...]).
        """
        return {
            "check_id": uuid4(),
            "reconciliation_run_id": reconciliation_run_id,
            "executed_at": executed_at,
            "statement_version_id": statement_version_id,
            "company_id": company_id,
            "cik": result.statement_identity.cik,
            "statement_type": result.statement_identity.statement_type.value,
            "fiscal_year": result.statement_identity.fiscal_year,
            "fiscal_period": result.statement_identity.fiscal_period.value,
            "version_sequence": result.statement_identity.version_sequence,
            "statement_date": statement_date,
            "rule_id": result.rule_id,
            "rule_category": result.rule_category.value,
            "status": result.status.value,
            "severity": MaterialityClass(result.severity).value,
            "expected_value": result.expected_value,
            "actual_value": result.actual_value,
            "delta_value": result.delta,
            "dimension_key": result.dimension_key,
            "dimension_labels": dict(result.dimension_labels) if result.dimension_labels else None,
            "notes": dict(result.notes) if result.notes else None,
        }

    @staticmethod
    def _map_to_domain(*, row: EdgarReconciliationCheck, cik: str) -> ReconciliationResult:
        """Map an ORM reconciliation check row to a domain ReconciliationResult."""
        expected = Decimal(str(row.expected_value)) if row.expected_value is not None else None
        actual = Decimal(str(row.actual_value)) if row.actual_value is not None else None
        delta = Decimal(str(row.delta_value)) if row.delta_value is not None else None

        return ReconciliationResult(
            statement_identity=NormalizedStatementIdentity(
                cik=cik,
                statement_type=StatementType(row.statement_type),
                fiscal_year=row.fiscal_year,
                fiscal_period=FiscalPeriod(row.fiscal_period),
                version_sequence=row.version_sequence,
            ),
            rule_id=row.rule_id,
            rule_category=ReconciliationRuleCategory(row.rule_category),
            status=ReconciliationStatus(row.status),
            severity=MaterialityClass(row.severity),
            expected_value=expected,
            actual_value=actual,
            delta=delta,
            dimension_key=row.dimension_key,
            dimension_labels=(
                {str(k): str(v) for k, v in row.dimension_labels.items()}
                if row.dimension_labels
                else None
            ),
            notes=row.notes,
        )


__all__ = ["SqlAlchemyEdgarReconciliationChecksRepository"]
