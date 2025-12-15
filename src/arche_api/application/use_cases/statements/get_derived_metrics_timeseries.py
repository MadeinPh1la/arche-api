# src/arche_api/application/use_cases/statements/get_derived_metrics_timeseries.py
# Copyright (c)
# SPDX-License-Identifier: MIT
"""Use case: Derived metrics time series from normalized EDGAR statements.

Purpose:
    Build a Bloomberg-class derived-metrics time series for one or more
    companies using canonical normalized EDGAR statement payloads and the
    domain derived-metrics engine. The resulting structure is deterministic
    and panel-friendly for valuation and analytics workflows.

Layer:
    application

Notes:
    - This use case is read-only.
    - It currently supports a universe expressed as CIKs.
    - Currency normalization is deferred to a later phase; metrics are
      computed in native statement currency.
"""

from __future__ import annotations

import logging
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import date
from typing import Any, cast

from arche_api.application.uow import UnitOfWork
from arche_api.domain.entities.canonical_statement_payload import (
    CanonicalStatementPayload,
)
from arche_api.domain.entities.edgar_derived_timeseries import (
    DerivedMetricsTimeSeriesPoint,
    build_derived_metrics_timeseries,
)
from arche_api.domain.enums.derived_metric import DerivedMetric
from arche_api.domain.enums.edgar import FiscalPeriod, StatementType
from arche_api.domain.exceptions.edgar import EdgarMappingError
from arche_api.domain.interfaces.repositories.edgar_statements_repository import (
    EdgarStatementsRepository as EdgarStatementsRepositoryProtocol,
)
from arche_api.domain.services.derived_metrics_engine import (
    DerivedMetricsEngine,
)

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class GetDerivedMetricsTimeSeriesRequest:
    """Request parameters for derived metrics time-series retrieval.

    Attributes:
        ciks:
            Universe of companies expressed as CIKs. All values are stripped
            of whitespace and empty entries are discarded.
        statement_type:
            Statement type to use as the primary source of fundamentals
            (e.g., INCOME_STATEMENT, BALANCE_SHEET).
        metrics:
            Optional subset of derived metrics to include. When None, all
            metrics in the derived-metrics registry are considered.
        frequency:
            Frequency of the time series. Allowed values (case-insensitive):
                - "annual": Uses fiscal_period == FY rows only.
                - "quarterly": Uses fiscal_period in {Q1, Q2, Q3, Q4}.
        from_date:
            Inclusive lower bound for statement_date. When None, defaults to
            1994-01-01 (approximate early EDGAR coverage).
        to_date:
            Inclusive upper bound for statement_date. When None, defaults to
            today's date.
    """

    ciks: Sequence[str]
    statement_type: StatementType
    metrics: Sequence[DerivedMetric] | None = None
    frequency: str = "annual"
    from_date: date | None = None
    to_date: date | None = None


class GetDerivedMetricsTimeSeriesUseCase:
    """Build a derived metrics time series from normalized EDGAR statements.

    Args:
        uow: Unit-of-work used to access the EDGAR statements repository.

    Returns:
        List of :class:`DerivedMetricsTimeSeriesPoint` instances representing
        a panel-style time series suitable for downstream analytics and
        valuation workflows.

    Raises:
        EdgarMappingError:
            If the request parameters are invalid (empty universe, invalid
            frequency, or an inverted date window).
    """

    def __init__(self, uow: UnitOfWork) -> None:
        """Initialize the use case.

        Args:
            uow: Application UnitOfWork abstraction used to resolve repositories.
        """
        self._uow = uow
        self._engine = DerivedMetricsEngine()

    async def execute(
        self,
        req: GetDerivedMetricsTimeSeriesRequest,
    ) -> list[DerivedMetricsTimeSeriesPoint]:
        """Execute derived-metrics time-series retrieval.

        Args:
            req: Parameters describing the universe and time window.

        Returns:
            Deterministically ordered list of
            :class:`DerivedMetricsTimeSeriesPoint` instances.

        Raises:
            EdgarMappingError:
                If the request parameters are invalid (empty universe, invalid
                frequency, or an inverted date window).
        """
        cleaned_ciks = sorted({c.strip() for c in req.ciks if c.strip()})
        if not cleaned_ciks:
            raise EdgarMappingError(
                "At least one non-empty CIK must be provided for derived metrics time series.",
            )

        from_date, to_date = self._normalize_window(req.from_date, req.to_date)

        frequency = req.frequency.lower()
        if frequency not in {"annual", "quarterly"}:
            raise EdgarMappingError(
                "Unsupported frequency for derived metrics time series; expected 'annual' or 'quarterly'.",
                details={"frequency": req.frequency},
            )

        if frequency == "annual":
            allowed_periods: set[FiscalPeriod] = {FiscalPeriod.FY}
        else:
            allowed_periods = {
                FiscalPeriod.Q1,
                FiscalPeriod.Q2,
                FiscalPeriod.Q3,
                FiscalPeriod.Q4,
            }

        logger.info(
            "edgar.get_derived_metrics_timeseries.start",
            extra={
                "ciks": cleaned_ciks,
                "statement_type": req.statement_type.value,
                "metrics": [m.value for m in (req.metrics or [])],
                "frequency": frequency,
                "from_date": from_date.isoformat(),
                "to_date": to_date.isoformat(),
            },
        )

        async with self._uow as tx:
            statements_repo = _get_edgar_statements_repository(tx)

            all_points: list[DerivedMetricsTimeSeriesPoint] = []
            for cik in cleaned_ciks:
                company_points = await self._collect_company_points(
                    statements_repo=statements_repo,
                    cik=cik,
                    statement_type=req.statement_type,
                    allowed_periods=allowed_periods,
                    from_date=from_date,
                    to_date=to_date,
                    metrics=req.metrics,
                    frequency=frequency,
                )
                all_points.extend(company_points)

        series = build_derived_metrics_timeseries(all_points)

        logger.info(
            "edgar.get_derived_metrics_timeseries.success",
            extra={
                "ciks": cleaned_ciks,
                "statement_type": req.statement_type.value,
                "frequency": frequency,
                "from_date": from_date.isoformat(),
                "to_date": to_date.isoformat(),
                "points": len(series),
            },
        )

        return series

    # ------------------------------------------------------------------ #
    # Internal helpers                                                   #
    # ------------------------------------------------------------------ #

    @staticmethod
    def _normalize_window(
        from_date: date | None,
        to_date: date | None,
    ) -> tuple[date, date]:
        """Normalize a (from_date, to_date) window into concrete bounds.

        Behavior:
            - If from_date is None, uses 1994-01-01 (early EDGAR coverage).
            - If to_date is None, uses today's date.
            - Raises EdgarMappingError if lower bound is after upper bound.

        Args:
            from_date: Optional lower bound for statement_date.
            to_date: Optional upper bound for statement_date.

        Returns:
            Tuple of (lower_bound, upper_bound) dates.

        Raises:
            EdgarMappingError: If lower_bound > upper_bound.
        """
        today = date.today()
        lower = from_date or date(1994, 1, 1)
        upper = to_date or today

        if lower > upper:
            raise EdgarMappingError(
                "from_date must be on or before to_date for derived metrics time series.",
                details={"from_date": lower.isoformat(), "to_date": upper.isoformat()},
            )

        return lower, upper

    async def _collect_company_points(
        self,
        *,
        statements_repo: EdgarStatementsRepositoryProtocol,
        cik: str,
        statement_type: StatementType,
        allowed_periods: set[FiscalPeriod],
        from_date: date,
        to_date: date,
        metrics: Sequence[DerivedMetric] | None,
        frequency: str,
    ) -> list[DerivedMetricsTimeSeriesPoint]:
        """Collect derived metrics points for a single company.

        For each fiscal year in the window, this helper loads all statement
        versions via the repository and then selects, per fiscal period/date,
        the latest version (highest version_sequence) with a non-None
        normalized payload. It then invokes the derived-metrics engine to
        compute derived metrics for each selected payload.
        """
        lower_year = from_date.year
        upper_year = to_date.year

        payloads: list[CanonicalStatementPayload] = []

        for fiscal_year in range(lower_year, upper_year + 1):
            versions = await statements_repo.list_statement_versions_for_company(
                cik=cik,
                statement_type=statement_type,
                fiscal_year=fiscal_year,
                fiscal_period=None,
            )

            candidates = [
                v
                for v in versions
                if v.fiscal_period in allowed_periods
                and from_date <= v.statement_date <= to_date
                and v.normalized_payload is not None
            ]

            if not candidates:
                continue

            by_key: dict[tuple[date, FiscalPeriod], CanonicalStatementPayload] = {}
            by_seq: dict[tuple[date, FiscalPeriod], int] = {}

            for v in candidates:
                key = (v.statement_date, v.fiscal_period)
                current_seq = by_seq.get(key)
                payload = v.normalized_payload
                if payload is None:  # pragma: no cover - defensive guard
                    continue

                if current_seq is None or v.version_sequence > current_seq:
                    by_seq[key] = v.version_sequence
                    by_key[key] = payload

            payloads.extend(by_key.values())

        # Sort payloads deterministically by statement_date / fiscal_period.
        payloads.sort(key=lambda p: (p.statement_date, p.fiscal_period.value))

        derived_points: list[DerivedMetricsTimeSeriesPoint] = []
        history: list[CanonicalStatementPayload] = []

        for payload in payloads:
            result = self._engine.compute(
                payload=payload,
                history=tuple(history),
                metrics=metrics,
            )

            if not result.values:
                # All requested metrics failed; skip creating a point.
                history.append(payload)
                continue

            point = DerivedMetricsTimeSeriesPoint(
                cik=payload.cik,
                statement_type=payload.statement_type,
                accounting_standard=payload.accounting_standard,
                statement_date=payload.statement_date,
                fiscal_year=payload.fiscal_year,
                fiscal_period=payload.fiscal_period,
                currency=payload.currency,
                metrics=result.values,
                normalized_payload_version_sequence=payload.source_version_sequence,
            )
            derived_points.append(point)
            history.append(payload)

        return derived_points


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
