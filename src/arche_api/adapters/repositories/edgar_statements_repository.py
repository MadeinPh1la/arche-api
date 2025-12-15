# src/arche_api/adapters/repositories/edgar_statements_repository.py
# Copyright (c)
# SPDX-License-Identifier: MIT
"""EDGAR statement versions repository (SQLAlchemy).

Purpose:
    Provide persistence and query operations for EDGAR statement versions,
    including support for storing and retrieving normalized statement payloads
    produced by the Normalized Statement Payload Engine.

Layer:
    adapters/repositories

Design:
    * Uses SQLAlchemy Core/ORM with AsyncSession.
    * Emits Prometheus-style metrics for latency and failures.
    * Maps between DB models and domain entities/value objects.
"""

from __future__ import annotations

import time
from collections.abc import Mapping, Sequence
from contextlib import suppress
from datetime import date
from decimal import Decimal, InvalidOperation
from typing import Any, cast
from uuid import uuid4

from sqlalchemy import Select, insert, select, update
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import aliased

from arche_api.adapters.repositories.base_repository import BaseRepository
from arche_api.domain.entities.canonical_statement_payload import (
    CanonicalStatementPayload,
)
from arche_api.domain.entities.edgar_company import EdgarCompanyIdentity
from arche_api.domain.entities.edgar_filing import EdgarFiling
from arche_api.domain.entities.edgar_statement_version import EdgarStatementVersion
from arche_api.domain.enums.canonical_statement_metric import (
    CanonicalStatementMetric,
)
from arche_api.domain.enums.edgar import (
    AccountingStandard,
    FilingType,
    FiscalPeriod,
    StatementType,
)
from arche_api.domain.exceptions.edgar import EdgarIngestionError
from arche_api.infrastructure.database.models.ref import Company
from arche_api.infrastructure.database.models.sec import Filing, StatementVersion
from arche_api.infrastructure.observability.metrics import (
    get_db_errors_total,
    get_db_operation_duration_seconds,
)


class EdgarStatementsRepository(BaseRepository[StatementVersion]):
    """SQLAlchemy-backed EDGAR statements repository."""

    _MODEL_NAME = "sec_statement_versions"

    def __init__(self, session: AsyncSession) -> None:
        """Initialize the repository.

        Args:
            session: Async SQLAlchemy session bound to the test or production
                database.
        """
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
        """Insert a single statement version.

        This is a thin convenience wrapper over
        :meth:`upsert_statement_versions`.
        """
        await self.upsert_statement_versions([version])

    async def upsert_statement_versions(
        self,
        versions: Sequence[EdgarStatementVersion],
    ) -> None:
        """Insert a batch of statement versions.

        Implementations:
            * Resolve `ref.companies` and `sec.filings` foreign keys by CIK and
              accession.
            * Insert new rows into `sec.statement_versions` using fresh UUIDs.
            * Store any attached normalized payloads as JSON, with a default
              `normalized_payload_version` of "v1" when unspecified.

        Args:
            versions: Statement version entities to persist.

        Raises:
            EdgarIngestionError: If the reference company or filing rows are
                missing for any version, or if the insert fails.
        """
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

                normalized_payload_dict: dict[str, Any] | None = None
                normalized_payload_version = v.normalized_payload_version or "v1"
                if v.normalized_payload is not None:
                    normalized_payload_dict = self._serialize_normalized_payload(
                        v.normalized_payload,
                    )

                row: dict[str, Any] = {
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
                    "normalized_payload": normalized_payload_dict,
                    "normalized_payload_version": normalized_payload_version,
                }

                payload.append(row)

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

    async def update_normalized_payload(
        self,
        *,
        company_cik: str,
        accession_id: str,
        statement_type: StatementType,
        version_sequence: int,
        payload: CanonicalStatementPayload,
        payload_version: str,
    ) -> None:
        """Update normalized payload fields for a single statement version.

        This method is used by the Normalized Statement Payload Engine to
        attach or refresh the canonical payload and its schema version for an
        existing statement version row. It does not modify any other metadata.

        Args:
            company_cik: CIK of the company that owns the statement version.
            accession_id: EDGAR accession ID of the underlying filing.
            statement_type: Statement type (e.g., INCOME_STATEMENT).
            version_sequence: Monotonic sequence number of the version to
                update.
            payload: Canonical normalized statement payload to store.
            payload_version: Stable identifier for the payload schema
                (e.g., "v1").

        Raises:
            EdgarIngestionError: If the company cannot be resolved or no
                matching `sec.statement_versions` row exists for the provided
                identity tuple, or if the update fails.
        """
        start = time.perf_counter()
        outcome = "success"

        try:
            company = await self._get_company_by_cik(company_cik)
            if company is None:
                raise EdgarIngestionError(
                    "Cannot update normalized payload; ref.company row not found.",
                    details={"cik": company_cik},
                )

            normalized_payload_dict = self._serialize_normalized_payload(payload)

            stmt = (
                update(StatementVersion)
                .where(
                    StatementVersion.company_id == company.company_id,
                    StatementVersion.accession_id == accession_id,
                    StatementVersion.statement_type == statement_type.value,
                    StatementVersion.version_sequence == version_sequence,
                )
                .values(
                    normalized_payload=normalized_payload_dict,
                    normalized_payload_version=payload_version,
                )
            )

            # Treat result as Any so mypy does not complain about rowcount.
            result: Any = await self._session.execute(stmt)
            affected = getattr(result, "rowcount", None)

            # If the backend reports a concrete 0 rowcount, treat this as a
            # hard error; if it reports None (unknown), we allow it.
            if affected == 0:
                raise EdgarIngestionError(
                    "No sec.statement_versions row matched for normalized payload update.",
                    details={
                        "cik": company_cik,
                        "accession_id": accession_id,
                        "statement_type": statement_type.value,
                        "version_sequence": version_sequence,
                    },
                )

        except Exception as exc:  # noqa: BLE001
            outcome = "error"
            with suppress(Exception):
                self._metrics_err.labels(
                    operation="update_normalized_payload",
                    model=self._MODEL_NAME,
                    reason=type(exc).__name__,
                ).inc()
            raise

        finally:
            with suppress(Exception):
                duration = time.perf_counter() - start
                self._metrics_hist.labels(
                    operation="update_normalized_payload",
                    model=self._MODEL_NAME,
                    outcome=outcome,
                ).observe(duration)

    # ------------------------------------------------------------------
    # QUERIES – legacy interface (date-window based)
    # ------------------------------------------------------------------

    async def get_latest_statement_version(
        self,
        company: EdgarCompanyIdentity,
        statement_type: StatementType,
        statement_date: date,
    ) -> EdgarStatementVersion:
        """Legacy API: return the latest statement version for a given date.

        This satisfies the older domain interface used in some callers.

        Raises:
            EdgarIngestionError: If no matching statement version exists.
        """
        start = time.perf_counter()
        outcome = "success"

        try:
            company_row = await self._get_company_by_cik(company.cik)
            if company_row is None:
                raise EdgarIngestionError(
                    "ref.company row not found for get_latest_statement_version.",
                    details={"cik": company.cik},
                )

            sv = aliased(StatementVersion)
            f = aliased(Filing)

            stmt: Select[Any] = (
                select(sv, f)
                .join(f, sv.filing_id == f.filing_id)
                .where(
                    sv.company_id == company_row.company_id,
                    sv.statement_type == statement_type.value,
                    sv.statement_date == statement_date,
                )
                .order_by(sv.version_sequence.desc(), sv.statement_version_id.asc())
                .limit(1)
            )

            res = await self._session.execute(stmt)
            row = res.first()
            if row is None:
                raise EdgarIngestionError(
                    "No statement version found for company/date.",
                    details={
                        "cik": company.cik,
                        "statement_type": statement_type.value,
                        "statement_date": statement_date.isoformat(),
                    },
                )

            sv_row, filing_row = cast(tuple[StatementVersion, Filing], row)
            return self._map_to_domain(company_row, filing_row, sv_row)

        except Exception as exc:  # noqa: BLE001
            outcome = "error"
            with suppress(Exception):
                self._metrics_err.labels(
                    operation="get_latest_statement_version",
                    model=self._MODEL_NAME,
                    reason=type(exc).__name__,
                ).inc()
            raise

        finally:
            with suppress(Exception):
                duration = time.perf_counter() - start
                self._metrics_hist.labels(
                    operation="get_latest_statement_version",
                    model=self._MODEL_NAME,
                    outcome=outcome,
                ).observe(duration)

    async def list_statement_versions(
        self,
        company: EdgarCompanyIdentity,
        statement_type: StatementType,
        from_date: date,
        to_date: date,
        include_restated: bool = False,
    ) -> Sequence[EdgarStatementVersion]:
        """Legacy API: list statement versions over a date range.

        See the domain interface for semantics.
        """
        start = time.perf_counter()
        outcome = "success"

        try:
            company_row = await self._get_company_by_cik(company.cik)
            if company_row is None:
                return []

            sv = aliased(StatementVersion)
            f = aliased(Filing)

            stmt: Select[Any] = (
                select(sv, f)
                .join(f, sv.filing_id == f.filing_id)
                .where(
                    sv.company_id == company_row.company_id,
                    sv.statement_type == statement_type.value,
                    sv.statement_date >= from_date,
                    sv.statement_date <= to_date,
                )
                .order_by(
                    sv.statement_date.asc(),
                    sv.version_sequence.asc(),
                    sv.statement_version_id.asc(),
                )
            )

            res = await self._session.execute(stmt)
            rows = cast(list[tuple[StatementVersion, Filing]], res.all())

            versions = [
                self._map_to_domain(company_row, filing_row, sv_row) for sv_row, filing_row in rows
            ]

            if include_restated:
                return versions

            # Filter down to latest non-restated per statement_date.
            by_date: dict[date, EdgarStatementVersion] = {}
            for v in versions:
                key = v.statement_date
                current = by_date.get(key)
                if v.is_restated:
                    # Skip restated rows when include_restated=False.
                    continue
                if current is None or v.version_sequence > current.version_sequence:
                    by_date[key] = v

            # Deterministic ordering: statement_date asc, version_sequence asc.
            return sorted(
                by_date.values(),
                key=lambda v: (v.statement_date, v.version_sequence),
            )

        except Exception as exc:  # noqa: BLE001
            outcome = "error"
            with suppress(Exception):
                self._metrics_err.labels(
                    operation="list_statement_versions",
                    model=self._MODEL_NAME,
                    reason=type(exc).__name__,
                ).inc()
            raise

        finally:
            with suppress(Exception):
                duration = time.perf_counter() - start
                self._metrics_hist.labels(
                    operation="list_statement_versions",
                    model=self._MODEL_NAME,
                    outcome=outcome,
                ).observe(duration)

    # ------------------------------------------------------------------
    # QUERIES – identity-based APIs used by new use cases
    # ------------------------------------------------------------------

    async def latest_statement_version_for_company(
        self,
        *,
        cik: str,
        statement_type: StatementType,
        fiscal_year: int,
        fiscal_period: FiscalPeriod,
    ) -> EdgarStatementVersion | None:
        """Return the latest statement version for a company/year/period.

        Args:
            cik: Company CIK.
            statement_type: Statement type to filter by.
            fiscal_year: Fiscal year to filter by.
            fiscal_period: Fiscal period (e.g., FY, Q1, Q2).

        Returns:
            The latest `EdgarStatementVersion`, or None if none exist.
        """
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
        """List all statement versions for a company/year/type (optionally period).

        Args:
            cik: Company CIK.
            statement_type: Statement type to filter by.
            fiscal_year: Fiscal year to filter by.
            fiscal_period: Optional fiscal period filter. If None, all periods
                within the year are returned.

        Returns:
            List of `EdgarStatementVersion` entities, ordered by
            (version_sequence ASC, statement_version_id ASC).
        """
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
        """Fetch reference companies by CIK into a lookup map."""
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
        """Fetch SEC filings by accession into a lookup map."""
        if not accessions:
            return {}

        stmt = select(Filing).where(Filing.accession.in_(list(accessions)))
        res = await self._session.execute(stmt)
        rows: list[Filing] = list(res.scalars().all())
        return {row.accession: row for row in rows}

    async def _get_company_by_cik(self, cik: str) -> Company | None:
        """Return the `Company` row for a given CIK, or None if missing."""
        stmt = select(Company).where(Company.cik == cik).limit(1)
        res = await self._session.execute(stmt)
        return res.scalar_one_or_none()

    @staticmethod
    def _map_to_domain(
        company_row: Company,
        filing_row: Filing,
        sv_row: StatementVersion,
    ) -> EdgarStatementVersion:
        """Map ORM rows into a domain `EdgarStatementVersion`.

        Args:
            company_row: Reference company row.
            filing_row: Filing row.
            sv_row: Statement version row.

        Returns:
            Mapped `EdgarStatementVersion` entity.

        Raises:
            EdgarIngestionError: If the company row is missing a CIK or the
                normalized payload cannot be mapped.
        """
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

        normalized_payload = EdgarStatementsRepository._map_normalized_payload(
            sv_row.normalized_payload,
        )

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
            normalized_payload=normalized_payload,
            normalized_payload_version=sv_row.normalized_payload_version,
        )

    # ------------------------------------------------------------------
    # Normalized payload mapping helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _serialize_normalized_payload(
        payload: CanonicalStatementPayload,
    ) -> dict[str, Any]:
        """Serialize a CanonicalStatementPayload into a JSON-serializable dict.

        Notes:
            - Decimal values are converted to strings to avoid loss of
              precision when stored as JSON.
            - Enum keys and values are serialized using their `.value`
              representation to keep the payload stable and readable.
        """
        core_metrics = {
            metric.value: str(amount) for metric, amount in payload.core_metrics.items()
        }
        extra_metrics = {key: str(amount) for key, amount in payload.extra_metrics.items()}

        return {
            "cik": payload.cik,
            "statement_type": payload.statement_type.value,
            "accounting_standard": payload.accounting_standard.value,
            "statement_date": payload.statement_date.isoformat(),
            "fiscal_year": payload.fiscal_year,
            "fiscal_period": payload.fiscal_period.value,
            "currency": payload.currency,
            "unit_multiplier": payload.unit_multiplier,
            "core_metrics": core_metrics,
            "extra_metrics": extra_metrics,
            "dimensions": dict(payload.dimensions),
            "source_accession_id": payload.source_accession_id,
            "source_taxonomy": payload.source_taxonomy,
            "source_version_sequence": payload.source_version_sequence,
        }

    @staticmethod
    def _map_normalized_payload(
        payload: Mapping[str, Any] | None,
    ) -> CanonicalStatementPayload | None:
        """Map a stored JSON payload into a CanonicalStatementPayload.

        Args:
            payload: Raw JSON mapping from the database, or None.

        Returns:
            A CanonicalStatementPayload instance, or None if the stored payload
            is None.

        Raises:
            EdgarIngestionError: If the payload structure is invalid or
                contains values that cannot be coerced into the expected
                types.
        """
        if payload is None:
            return None

        try:
            raw_statement_date = payload["statement_date"]
            if isinstance(raw_statement_date, str):
                statement_date = date.fromisoformat(raw_statement_date)
            elif isinstance(raw_statement_date, date):
                statement_date = raw_statement_date
            else:
                raise EdgarIngestionError(
                    "Invalid type for statement_date in normalized payload.",
                    details={"type": type(raw_statement_date).__name__},
                )

            statement_type = StatementType(payload["statement_type"])
            accounting_standard = AccountingStandard(payload["accounting_standard"])
            fiscal_period = FiscalPeriod(payload["fiscal_period"])

            currency = str(payload["currency"])
            cik = str(payload["cik"])
            fiscal_year = int(payload["fiscal_year"])
            unit_multiplier = int(payload["unit_multiplier"])

            core_metrics_raw = cast(Mapping[str, Any], payload.get("core_metrics", {}))
            extra_metrics_raw = cast(Mapping[str, Any], payload.get("extra_metrics", {}))
            dimensions_raw = cast(Mapping[str, Any], payload.get("dimensions", {}))

            core_metrics: dict[CanonicalStatementMetric, Decimal] = {}
            for key, value in core_metrics_raw.items():
                metric = CanonicalStatementMetric(key)
                core_metrics[metric] = EdgarStatementsRepository._to_decimal(
                    value,
                    metric_name=metric.value,
                )

            extra_metrics: dict[str, Decimal] = {}
            for key, value in extra_metrics_raw.items():
                extra_metrics[str(key)] = EdgarStatementsRepository._to_decimal(
                    value,
                    metric_name=str(key),
                )

            dimensions: dict[str, str] = {str(k): str(v) for k, v in dimensions_raw.items()}

            source_accession_id = str(payload["source_accession_id"])
            source_taxonomy = str(payload["source_taxonomy"])
            source_version_sequence = int(payload["source_version_sequence"])

            return CanonicalStatementPayload(
                cik=cik,
                statement_type=statement_type,
                accounting_standard=accounting_standard,
                statement_date=statement_date,
                fiscal_year=fiscal_year,
                fiscal_period=fiscal_period,
                currency=currency,
                unit_multiplier=unit_multiplier,
                core_metrics=core_metrics,
                extra_metrics=extra_metrics,
                dimensions=dimensions,
                source_accession_id=source_accession_id,
                source_taxonomy=source_taxonomy,
                source_version_sequence=source_version_sequence,
            )

        except EdgarIngestionError:
            # Bubble up explicit ingestion errors unchanged.
            raise
        except Exception as exc:  # noqa: BLE001
            raise EdgarIngestionError(
                "Failed to map normalized payload from sec.statement_versions.",
                details={"reason": type(exc).__name__},
            ) from exc

    @staticmethod
    def _to_decimal(value: Any, *, metric_name: str) -> Decimal:
        """Coerce a stored JSON value into a Decimal.

        Args:
            value: Raw JSON value (string, int, float, etc.).
            metric_name: Name of the metric for error reporting.

        Returns:
            Decimal representation of the value.

        Raises:
            EdgarIngestionError: If the value cannot be converted to Decimal.
        """
        try:
            return Decimal(str(value))
        except (InvalidOperation, TypeError) as exc:
            raise EdgarIngestionError(
                "Invalid numeric value in normalized payload.",
                details={"metric": metric_name, "value": repr(value)},
            ) from exc
