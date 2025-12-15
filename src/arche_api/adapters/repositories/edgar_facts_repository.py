# src/arche_api/adapters/repositories/edgar_facts_repository.py
# Copyright (c)
# SPDX-License-Identifier: MIT
"""EDGAR normalized facts repository (SQLAlchemy).

Purpose:
    Provide persistence and query operations for normalized EDGAR facts
    derived from canonical statement payloads. This repository implements
    the domain-level EdgarFactsRepository protocol.

Layer:
    adapters/repositories
"""

from __future__ import annotations

import time
from collections.abc import Mapping, Sequence
from contextlib import suppress
from decimal import Decimal
from typing import Any, cast
from uuid import UUID, uuid4

from sqlalchemy import Select, delete, insert, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import aliased

from arche_api.adapters.repositories.base_repository import BaseRepository
from arche_api.domain.entities.edgar_dq import NormalizedStatementIdentity
from arche_api.domain.entities.edgar_normalized_fact import EdgarNormalizedFact
from arche_api.domain.enums.edgar import (
    AccountingStandard,
    FiscalPeriod,
    StatementType,
)
from arche_api.domain.exceptions.edgar import EdgarIngestionError
from arche_api.infrastructure.database.models.ref import Company
from arche_api.infrastructure.database.models.sec import (
    EdgarNormalizedFact as EdgarNormalizedFactModel,
)
from arche_api.infrastructure.database.models.sec import StatementVersion
from arche_api.infrastructure.observability.metrics import (
    get_db_errors_total,
    get_db_operation_duration_seconds,
)


class EdgarFactsRepository(BaseRepository[EdgarNormalizedFactModel]):
    """SQLAlchemy-backed repository for normalized EDGAR facts."""

    _MODEL_NAME = "sec_edgar_normalized_facts"

    def __init__(self, session: AsyncSession) -> None:
        """Initialize the repository.

        Args:
            session:
                Async SQLAlchemy session bound to the test or production
                database.
        """
        super().__init__(session=session)
        self._metrics_hist = get_db_operation_duration_seconds()
        self._metrics_err = get_db_errors_total()

    # ------------------------------------------------------------------ #
    # Public API                                                         #
    # ------------------------------------------------------------------ #

    async def replace_facts_for_statement(
        self,
        identity: NormalizedStatementIdentity,
        facts: Sequence[EdgarNormalizedFact],
    ) -> None:
        """Replace all facts for a given statement identity.

        This operation is executed atomically within the current UnitOfWork
        transaction:

            1. Resolve the target `sec.statement_versions` row from the
               normalized statement identity.
            2. Delete any existing `sec.edgar_normalized_facts` rows for that
               statement version.
            3. Insert the provided facts (if any), maintaining deterministic
               ordering and stable identities via UUIDs.
        """
        start = time.perf_counter()
        outcome = "success"

        try:
            sv_row, company_row = await self._resolve_statement_version(identity)

            delete_stmt = delete(EdgarNormalizedFactModel).where(
                EdgarNormalizedFactModel.statement_version_id == sv_row.statement_version_id,
            )
            await self._session.execute(delete_stmt)

            if not facts:
                return

            payload: list[dict[str, Any]] = [
                self._to_row_dict(
                    fact=fact,
                    statement_version_id=sv_row.statement_version_id,
                    company_id=company_row.company_id,
                )
                for fact in facts
            ]

            stmt = insert(EdgarNormalizedFactModel).values(payload)
            await self._session.execute(stmt)

        except Exception as exc:  # noqa: BLE001
            outcome = "error"
            with suppress(Exception):
                self._metrics_err.labels(
                    operation="replace_facts_for_statement",
                    model=self._MODEL_NAME,
                    reason=type(exc).__name__,
                ).inc()
            raise
        finally:
            with suppress(Exception):
                duration = time.perf_counter() - start
                self._metrics_hist.labels(
                    operation="replace_facts_for_statement",
                    model=self._MODEL_NAME,
                    outcome=outcome,
                ).observe(duration)

    async def list_facts_for_statement(
        self,
        identity: NormalizedStatementIdentity,
        metric_filter: Sequence[str] | None = None,
    ) -> list[EdgarNormalizedFact]:
        """Return all facts for a given statement identity.

        Results are deterministically ordered by:

            (metric_code ASC, dimension_key ASC, fact_id ASC)

        Optionally filters by a set of metric codes.
        """
        start = time.perf_counter()
        outcome = "success"

        try:
            sv_row, company_row = await self._resolve_statement_version(identity)

            ef = aliased(EdgarNormalizedFactModel)

            conditions: list[Any] = [ef.statement_version_id == sv_row.statement_version_id]
            if metric_filter:
                conditions.append(ef.metric_code.in_(list(metric_filter)))

            stmt: Select[Any] = (
                select(ef)
                .where(*conditions)
                .order_by(
                    ef.metric_code.asc(),
                    ef.dimension_key.asc(),
                    ef.fact_id.asc(),
                )
            )

            res = await self._session.execute(stmt)
            rows: list[EdgarNormalizedFactModel] = list(res.scalars().all())

            cik = company_row.cik or identity.cik

            return [
                self._map_to_domain(
                    row=row,
                    cik=cik,
                )
                for row in rows
            ]

        except Exception as exc:  # noqa: BLE001
            outcome = "error"
            with suppress(Exception):
                self._metrics_err.labels(
                    operation="list_facts_for_statement",
                    model=self._MODEL_NAME,
                    reason=type(exc).__name__,
                ).inc()
            raise
        finally:
            with suppress(Exception):
                duration = time.perf_counter() - start
                self._metrics_hist.labels(
                    operation="list_facts_for_statement",
                    model=self._MODEL_NAME,
                    outcome=outcome,
                ).observe(duration)

    async def list_facts_history(
        self,
        *,
        cik: str,
        statement_type: str,
        metric_code: str,
        limit: int = 8,
    ) -> list[EdgarNormalizedFact]:
        """Return a small historical slice of facts for a metric.

        The history is ordered by:

            (statement_date ASC, version_sequence ASC, dimension_key ASC, fact_id ASC)

        This is intended for local DQ / anomaly detection where a short
        trailing window is sufficient.
        """
        start = time.perf_counter()
        outcome = "success"

        try:
            ef = aliased(EdgarNormalizedFactModel)

            stmt: Select[Any] = (
                select(ef)
                .where(
                    ef.cik == cik,
                    ef.statement_type == statement_type,
                    ef.metric_code == metric_code,
                )
                .order_by(
                    ef.statement_date.asc(),
                    ef.version_sequence.asc(),
                    ef.dimension_key.asc(),
                    ef.fact_id.asc(),
                )
                .limit(limit)
            )

            res = await self._session.execute(stmt)
            rows: list[EdgarNormalizedFactModel] = list(res.scalars().all())

            return [
                self._map_to_domain(
                    row=row,
                    cik=cik,
                )
                for row in rows
            ]

        except Exception as exc:  # noqa: BLE001
            outcome = "error"
            with suppress(Exception):
                self._metrics_err.labels(
                    operation="list_facts_history",
                    model=self._MODEL_NAME,
                    reason=type(exc).__name__,
                ).inc()
            raise
        finally:
            with suppress(Exception):
                duration = time.perf_counter() - start
                self._metrics_hist.labels(
                    operation="list_facts_history",
                    model=self._MODEL_NAME,
                    outcome=outcome,
                ).observe(duration)

    # ------------------------------------------------------------------ #
    # Internal helpers                                                   #
    # ------------------------------------------------------------------ #

    async def _resolve_statement_version(
        self,
        identity: NormalizedStatementIdentity,
    ) -> tuple[StatementVersion, Company]:
        """Resolve the StatementVersion + Company rows for a statement identity."""
        company_row = await self._get_company_by_cik(identity.cik)
        if company_row is None or company_row.cik is None:
            raise EdgarIngestionError(
                "ref.company row not found for normalized fact operation.",
                details={"cik": identity.cik},
            )

        sv = aliased(StatementVersion)

        stmt: Select[Any] = (
            select(sv)
            .where(
                sv.company_id == company_row.company_id,
                sv.statement_type == identity.statement_type.value,
                sv.fiscal_year == identity.fiscal_year,
                sv.fiscal_period == identity.fiscal_period.value,
                sv.version_sequence == identity.version_sequence,
            )
            .order_by(sv.statement_version_id.asc())
            .limit(1)
        )

        res = await self._session.execute(stmt)
        sv_row = cast(StatementVersion | None, res.scalar_one_or_none())
        if sv_row is None:
            raise EdgarIngestionError(
                "sec.statement_versions row not found for normalized fact operation.",
                details={
                    "cik": identity.cik,
                    "statement_type": identity.statement_type.value,
                    "fiscal_year": identity.fiscal_year,
                    "fiscal_period": identity.fiscal_period.value,
                    "version_sequence": identity.version_sequence,
                },
            )

        return sv_row, company_row

    async def _get_company_by_cik(self, cik: str) -> Company | None:
        """Return the Company row for a given CIK, or None if missing."""
        stmt = select(Company).where(Company.cik == cik).limit(1)
        res = await self._session.execute(stmt)
        return res.scalar_one_or_none()

    @staticmethod
    def _to_row_dict(
        *,
        fact: EdgarNormalizedFact,
        statement_version_id: UUID,
        company_id: UUID,
    ) -> dict[str, Any]:
        """Convert a domain fact into a row dict for insertion."""
        dimensions: Mapping[str, str] = fact.dimensions

        return {
            "fact_id": uuid4(),
            "statement_version_id": statement_version_id,
            "company_id": company_id,
            "cik": fact.cik,
            "statement_type": fact.statement_type.value,
            "accounting_standard": fact.accounting_standard.value,
            "fiscal_year": fact.fiscal_year,
            "fiscal_period": fact.fiscal_period.value,
            "statement_date": fact.statement_date,
            "version_sequence": fact.version_sequence,
            "metric_code": fact.metric_code,
            "metric_label": fact.metric_label,
            "unit": fact.unit,
            "period_start": fact.period_start,
            "period_end": fact.period_end,
            "value": fact.value,
            "dimension_key": fact.dimension_key,
            "dimension": dict(dimensions),
            "source_line_item": fact.source_line_item,
        }

    @staticmethod
    def _map_to_domain(
        *,
        row: EdgarNormalizedFactModel,
        cik: str,
    ) -> EdgarNormalizedFact:
        """Map an ORM fact row to a domain EdgarNormalizedFact."""
        dimensions_raw = cast(Mapping[str, Any] | None, row.dimension)
        dimensions: Mapping[str, str] = (
            {str(k): str(v) for k, v in dimensions_raw.items()} if dimensions_raw else {}
        )

        # Ensure we always hand a Decimal to the domain entity.
        value = Decimal(str(row.value))

        statement_type = StatementType(row.statement_type)
        accounting_standard = AccountingStandard(row.accounting_standard)
        fiscal_period = FiscalPeriod(row.fiscal_period)

        return EdgarNormalizedFact(
            cik=cik,
            statement_type=statement_type,
            accounting_standard=accounting_standard,
            fiscal_year=row.fiscal_year,
            fiscal_period=fiscal_period,
            statement_date=row.statement_date,
            version_sequence=row.version_sequence,
            metric_code=row.metric_code,
            metric_label=row.metric_label,
            unit=row.unit,
            period_start=row.period_start,
            period_end=row.period_end,
            value=value,
            dimensions=dimensions,
            dimension_key=row.dimension_key,
            source_line_item=row.source_line_item,
        )
