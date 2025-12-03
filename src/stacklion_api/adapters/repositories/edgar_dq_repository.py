# src/stacklion_api/adapters/repositories/edgar_dq_repository.py
# Copyright (c)
# SPDX-License-Identifier: MIT
"""EDGAR data-quality repository (SQLAlchemy).

Purpose:
    Provide persistence and query operations for EDGAR data-quality runs,
    fact-level quality flags, and rule-level anomalies. Implements the
    EdgarDQRepository protocol.

Layer:
    adapters/repositories
"""

from __future__ import annotations

import time
from collections.abc import Mapping, Sequence
from contextlib import suppress
from typing import Any, cast
from uuid import UUID, uuid4

from sqlalchemy import Select, insert, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import aliased

from stacklion_api.adapters.repositories.base_repository import BaseRepository
from stacklion_api.domain.entities.edgar_dq import (
    EdgarDQAnomaly,
    EdgarDQRun,
    EdgarFactQuality,
    NormalizedStatementIdentity,
)
from stacklion_api.domain.enums.edgar import MaterialityClass
from stacklion_api.domain.exceptions.edgar import EdgarIngestionError
from stacklion_api.infrastructure.database.models.ref import Company
from stacklion_api.infrastructure.database.models.sec import (
    EdgarDQAnomaly as EdgarDQAnomalyModel,
)
from stacklion_api.infrastructure.database.models.sec import (
    EdgarDQRun as EdgarDQRunModel,
)
from stacklion_api.infrastructure.database.models.sec import (
    EdgarFactQuality as EdgarFactQualityModel,
)
from stacklion_api.infrastructure.database.models.sec import StatementVersion
from stacklion_api.infrastructure.observability.metrics import (
    get_db_errors_total,
    get_db_operation_duration_seconds,
)


class EdgarDQRepository(BaseRepository[EdgarDQRunModel]):
    """SQLAlchemy-backed EDGAR data-quality repository."""

    _MODEL_NAME = "sec_edgar_dq"

    def __init__(self, session: AsyncSession) -> None:
        """Initialize the repository."""
        super().__init__(session=session)
        self._metrics_hist = get_db_operation_duration_seconds()
        self._metrics_err = get_db_errors_total()

    # ------------------------------------------------------------------ #
    # Public API                                                         #
    # ------------------------------------------------------------------ #

    async def create_run(
        self,
        run: EdgarDQRun,
        fact_quality: Sequence[EdgarFactQuality],
        anomalies: Sequence[EdgarDQAnomaly],
    ) -> None:
        """Persist a DQ run and its associated artifacts."""
        start = time.perf_counter()
        outcome = "success"

        try:
            statement_version_id: UUID | None = None
            cik: str | None = None
            statement_type: str | None = None
            fiscal_year: int | None = None
            fiscal_period: str | None = None
            version_sequence: int | None = None

            identity = run.statement_identity
            if identity is not None:
                (
                    statement_version_id,
                    cik,
                    statement_type,
                    fiscal_year,
                    fiscal_period,
                    version_sequence,
                ) = await self._resolve_statement_identity(identity)

            dq_run_uuid = UUID(run.dq_run_id)

            run_row = {
                "dq_run_id": dq_run_uuid,
                "statement_version_id": statement_version_id,
                "cik": cik,
                "statement_type": statement_type,
                "fiscal_year": fiscal_year,
                "fiscal_period": fiscal_period,
                "version_sequence": version_sequence,
                "rule_set_version": run.rule_set_version,
                "scope_type": run.scope_type,
                "executed_at": run.executed_at,
            }

            await self._session.execute(insert(EdgarDQRunModel).values([run_row]))

            fq_rows: list[dict[str, Any]] = []
            for fq in fact_quality:
                fq_rows.append(
                    self._fact_quality_to_row(
                        fq=fq,
                        dq_run_uuid=dq_run_uuid,
                        statement_version_id=statement_version_id,
                        cik=cik,
                        statement_type=statement_type,
                        fiscal_year=fiscal_year,
                        fiscal_period=fiscal_period,
                        version_sequence=version_sequence,
                    ),
                )

            if fq_rows:
                await self._session.execute(insert(EdgarFactQualityModel).values(fq_rows))

            anomaly_rows: list[dict[str, Any]] = []
            for anomaly in anomalies:
                anomaly_rows.append(
                    self._anomaly_to_row(
                        anomaly=anomaly,
                        dq_run_uuid=dq_run_uuid,
                        statement_version_id=statement_version_id,
                    ),
                )

            if anomaly_rows:
                await self._session.execute(insert(EdgarDQAnomalyModel).values(anomaly_rows))

        except Exception as exc:  # noqa: BLE001
            outcome = "error"
            with suppress(Exception):
                self._metrics_err.labels(
                    operation="create_run",
                    model=self._MODEL_NAME,
                    reason=type(exc).__name__,
                ).inc()
            raise
        finally:
            with suppress(Exception):
                duration = time.perf_counter() - start
                self._metrics_hist.labels(
                    operation="create_run",
                    model=self._MODEL_NAME,
                    outcome=outcome,
                ).observe(duration)

    async def latest_run_for_statement(
        self,
        identity: NormalizedStatementIdentity,
    ) -> EdgarDQRun | None:
        """Return the latest DQ run for a given statement identity."""
        start = time.perf_counter()
        outcome = "success"

        try:
            (
                statement_version_id,
                cik,
                statement_type,
                fiscal_year,
                fiscal_period,
                version_sequence,
            ) = await self._resolve_statement_identity(identity)

            dr = aliased(EdgarDQRunModel)

            stmt: Select[Any] = (
                select(dr)
                .where(
                    dr.cik == cik,
                    dr.statement_type == statement_type,
                    dr.fiscal_year == fiscal_year,
                    dr.fiscal_period == fiscal_period,
                    dr.version_sequence == version_sequence,
                    dr.statement_version_id == statement_version_id,
                )
                .order_by(dr.executed_at.desc(), dr.dq_run_id.asc())
                .limit(1)
            )

            res = await self._session.execute(stmt)
            row = cast(EdgarDQRunModel | None, res.scalar_one_or_none())
            if row is None:
                return None

            return self._map_run_to_domain(row)

        except Exception as exc:  # noqa: BLE001
            outcome = "error"
            with suppress(Exception):
                self._metrics_err.labels(
                    operation="latest_run_for_statement",
                    model=self._MODEL_NAME,
                    reason=type(exc).__name__,
                ).inc()
            raise
        finally:
            with suppress(Exception):
                duration = time.perf_counter() - start
                self._metrics_hist.labels(
                    operation="latest_run_for_statement",
                    model=self._MODEL_NAME,
                    outcome=outcome,
                ).observe(duration)

    async def list_anomalies_for_run(
        self,
        dq_run_id: str,
        min_severity: MaterialityClass | None = None,
        limit: int = 200,
    ) -> list[EdgarDQAnomaly]:
        """List anomalies for a given DQ run."""
        start = time.perf_counter()
        outcome = "success"

        try:
            dq_run_uuid = UUID(dq_run_id)
            da = aliased(EdgarDQAnomalyModel)

            stmt: Select[Any] = (
                select(da)
                .where(da.dq_run_id == dq_run_uuid)
                .order_by(
                    da.severity.desc(),
                    da.rule_code.asc(),
                    da.anomaly_id.asc(),
                )
            )

            res = await self._session.execute(stmt)
            rows: list[EdgarDQAnomalyModel] = list(res.scalars().all())

            anomalies = [self._map_anomaly_to_domain(row) for row in rows]

            if min_severity is not None:
                rank = _materiality_rank(min_severity)
                anomalies = [a for a in anomalies if _materiality_rank(a.severity) >= rank]

            return anomalies[:limit]

        except Exception as exc:  # noqa: BLE001
            outcome = "error"
            with suppress(Exception):
                self._metrics_err.labels(
                    operation="list_anomalies_for_run",
                    model=self._MODEL_NAME,
                    reason=type(exc).__name__,
                ).inc()
            raise
        finally:
            with suppress(Exception):
                duration = time.perf_counter() - start
                self._metrics_hist.labels(
                    operation="list_anomalies_for_run",
                    model=self._MODEL_NAME,
                    outcome=outcome,
                ).observe(duration)

    async def list_anomalies_for_statement(
        self,
        identity: NormalizedStatementIdentity,
        min_severity: MaterialityClass | None = None,
        limit: int = 200,
    ) -> list[EdgarDQAnomaly]:
        """List anomalies associated with a statement identity."""
        run = await self.latest_run_for_statement(identity)
        if run is None:
            return []

        return await self.list_anomalies_for_run(
            dq_run_id=run.dq_run_id,
            min_severity=min_severity,
            limit=limit,
        )

    async def list_fact_quality_for_statement(
        self,
        identity: NormalizedStatementIdentity,
    ) -> list[EdgarFactQuality]:
        """Return fact-level quality information for a statement identity."""
        start = time.perf_counter()
        outcome = "success"

        try:
            (
                _statement_version_id,
                cik,
                statement_type,
                fiscal_year,
                fiscal_period,
                version_sequence,
            ) = await self._resolve_statement_identity(identity)

            fq = aliased(EdgarFactQualityModel)

            stmt: Select[Any] = (
                select(fq)
                .where(
                    fq.cik == cik,
                    fq.statement_type == statement_type,
                    fq.fiscal_year == fiscal_year,
                    fq.fiscal_period == fiscal_period,
                    fq.version_sequence == version_sequence,
                )
                .order_by(
                    fq.metric_code.asc(),
                    fq.dimension_key.asc(),
                    fq.fact_quality_id.asc(),
                )
            )

            res = await self._session.execute(stmt)
            rows: list[EdgarFactQualityModel] = list(res.scalars().all())

            return [self._map_fact_quality_to_domain(row) for row in rows]

        except Exception as exc:  # noqa: BLE001
            outcome = "error"
            with suppress(Exception):
                self._metrics_err.labels(
                    operation="list_fact_quality_for_statement",
                    model=self._MODEL_NAME,
                    reason=type(exc).__name__,
                ).inc()
            raise
        finally:
            with suppress(Exception):
                duration = time.perf_counter() - start
                self._metrics_hist.labels(
                    operation="list_fact_quality_for_statement",
                    model=self._MODEL_NAME,
                    outcome=outcome,
                ).observe(duration)

    # ------------------------------------------------------------------ #
    # Internal helpers                                                   #
    # ------------------------------------------------------------------ #

    async def _resolve_statement_identity(
        self,
        identity: NormalizedStatementIdentity,
    ) -> tuple[UUID, str, str, int, str, int]:
        """Resolve statement version and identity fields for a statement."""
        company_row = await self._get_company_by_cik(identity.cik)
        if company_row is None or company_row.cik is None:
            raise EdgarIngestionError(
                "ref.company row not found for DQ operation.",
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
                "sec.statement_versions row not found for DQ operation.",
                details={
                    "cik": identity.cik,
                    "statement_type": identity.statement_type.value,
                    "fiscal_year": identity.fiscal_year,
                    "fiscal_period": identity.fiscal_period.value,
                    "version_sequence": identity.version_sequence,
                },
            )

        cik = company_row.cik
        if cik is None:
            raise EdgarIngestionError(
                "ref.company has null CIK; cannot resolve DQ identity.",
                details={"company_id": str(company_row.company_id)},
            )

        return (
            sv_row.statement_version_id,
            cik,
            sv_row.statement_type,
            sv_row.fiscal_year,
            sv_row.fiscal_period,
            sv_row.version_sequence,
        )

    async def _get_company_by_cik(self, cik: str) -> Company | None:
        """Return the Company row for a given CIK, or None if missing."""
        stmt = select(Company).where(Company.cik == cik).limit(1)
        res = await self._session.execute(stmt)
        return res.scalar_one_or_none()

    @staticmethod
    def _map_run_to_domain(row: EdgarDQRunModel) -> EdgarDQRun:
        """Map a DQ run ORM row to a domain EdgarDQRun."""
        identity: NormalizedStatementIdentity | None = None
        if (
            row.cik is not None
            and row.statement_type is not None
            and row.fiscal_year is not None
            and row.fiscal_period is not None
            and row.version_sequence is not None
        ):
            from stacklion_api.domain.enums.edgar import FiscalPeriod, StatementType

            identity = NormalizedStatementIdentity(
                cik=row.cik,
                statement_type=StatementType(row.statement_type),
                fiscal_year=row.fiscal_year,
                fiscal_period=FiscalPeriod(row.fiscal_period),
                version_sequence=row.version_sequence,
            )

        return EdgarDQRun(
            dq_run_id=str(row.dq_run_id),
            statement_identity=identity,
            rule_set_version=row.rule_set_version,
            scope_type=row.scope_type,
            executed_at=row.executed_at,
        )

    @staticmethod
    def _map_anomaly_to_domain(row: EdgarDQAnomalyModel) -> EdgarDQAnomaly:
        """Map a DQ anomaly ORM row to a domain EdgarDQAnomaly."""
        severity = MaterialityClass(row.severity)

        details: Mapping[str, Any] | None = row.details

        # statement_identity is intentionally omitted here; callers that need it
        # should join via latest_run_for_statement.
        return EdgarDQAnomaly(
            dq_run_id=str(row.dq_run_id),
            statement_identity=None,
            metric_code=row.metric_code,
            dimension_key=row.dimension_key,
            rule_code=row.rule_code,
            severity=severity,
            message=row.message,
            details=details,
        )

    @staticmethod
    def _map_fact_quality_to_domain(row: EdgarFactQualityModel) -> EdgarFactQuality:
        """Map a fact-quality ORM row to a domain EdgarFactQuality."""
        from stacklion_api.domain.enums.edgar import FiscalPeriod, StatementType

        severity = MaterialityClass(row.severity)

        identity = NormalizedStatementIdentity(
            cik=row.cik,
            statement_type=StatementType(row.statement_type),
            fiscal_year=row.fiscal_year,
            fiscal_period=FiscalPeriod(row.fiscal_period),
            version_sequence=row.version_sequence,
        )

        details: Mapping[str, Any] | None = row.details

        return EdgarFactQuality(
            dq_run_id=str(row.dq_run_id),
            statement_identity=identity,
            metric_code=row.metric_code,
            dimension_key=row.dimension_key,
            severity=severity,
            is_present=row.is_present,
            is_non_negative=row.is_non_negative,
            is_consistent_with_history=row.is_consistent_with_history,
            has_known_issue=row.has_known_issue,
            details=details,
        )

    @staticmethod
    def _fact_quality_to_row(
        *,
        fq: EdgarFactQuality,
        dq_run_uuid: UUID,
        statement_version_id: UUID | None,
        cik: str | None,
        statement_type: str | None,
        fiscal_year: int | None,
        fiscal_period: str | None,
        version_sequence: int | None,
    ) -> dict[str, Any]:
        """Convert a fact-quality domain entity into a row dict."""
        severity_value = fq.severity.value
        identity = fq.statement_identity

        if identity is None:
            raise EdgarIngestionError(
                "Fact quality entity is missing statement identity.",
                details={"metric_code": fq.metric_code, "dimension_key": fq.dimension_key},
            )

        return {
            "fact_quality_id": uuid4(),
            "dq_run_id": dq_run_uuid,
            "statement_version_id": statement_version_id,
            "cik": cik or identity.cik,
            "statement_type": statement_type or identity.statement_type.value,
            "fiscal_year": fiscal_year or identity.fiscal_year,
            "fiscal_period": fiscal_period or identity.fiscal_period.value,
            "version_sequence": version_sequence or identity.version_sequence,
            "metric_code": fq.metric_code,
            "dimension_key": fq.dimension_key,
            "severity": severity_value,
            "is_present": fq.is_present,
            "is_non_negative": fq.is_non_negative,
            "is_consistent_with_history": fq.is_consistent_with_history,
            "has_known_issue": fq.has_known_issue,
            "details": dict(fq.details) if fq.details is not None else None,
        }

    @staticmethod
    def _anomaly_to_row(
        *,
        anomaly: EdgarDQAnomaly,
        dq_run_uuid: UUID,
        statement_version_id: UUID | None,
    ) -> dict[str, Any]:
        """Convert a DQ anomaly domain entity into a row dict."""
        severity_value = anomaly.severity.value

        return {
            "anomaly_id": uuid4(),
            "dq_run_id": dq_run_uuid,
            "statement_version_id": statement_version_id,
            "metric_code": anomaly.metric_code,
            "dimension_key": anomaly.dimension_key,
            "rule_code": anomaly.rule_code,
            "severity": severity_value,
            "message": anomaly.message,
            "details": dict(anomaly.details) if anomaly.details is not None else None,
        }


def _materiality_rank(severity: MaterialityClass) -> int:
    """Return a stable numeric rank for MaterialityClass values.

    This avoids relying on Enum comparison semantics.
    """
    order = {
        MaterialityClass.NONE: 0,
        MaterialityClass.LOW: 1,
        MaterialityClass.MEDIUM: 2,
        MaterialityClass.HIGH: 3,
    }
    return order.get(severity, 0)
