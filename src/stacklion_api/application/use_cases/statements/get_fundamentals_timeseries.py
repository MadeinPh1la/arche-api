# src/stacklion_api/application/use_cases/statements/get_fundamentals_timeseries.py
# Copyright (c)
# SPDX-License-Identifier: MIT
"""Use case: Fundamentals time series from normalized EDGAR statements.

Purpose:
    Build an analytics-grade fundamentals time series for one or more
    companies using canonical normalized EDGAR statement payloads. The
    resulting structure is deterministic and panel-friendly for
    backtesting and modeling.

Layer:
    application

Notes:
    - This use case is read-only.
    - It currently supports a universe expressed as CIKs.
      A later phase can extend this to tickers or mixed identifiers
      by resolving through reference data.
"""

from __future__ import annotations

import logging
from collections.abc import Iterable, Sequence
from dataclasses import dataclass
from datetime import date
from typing import Any, cast

from stacklion_api.application.uow import UnitOfWork
from stacklion_api.domain.entities.canonical_statement_payload import (
    CanonicalStatementPayload,
)
from stacklion_api.domain.entities.edgar_fundamentals_timeseries import (
    FundamentalsTimeSeriesPoint,
    build_fundamentals_timeseries,
)
from stacklion_api.domain.enums.canonical_statement_metric import CanonicalStatementMetric
from stacklion_api.domain.enums.edgar import FiscalPeriod, StatementType
from stacklion_api.domain.exceptions.edgar import EdgarMappingError
from stacklion_api.domain.interfaces.repositories.edgar_statements_repository import (
    EdgarStatementsRepository as EdgarStatementsRepositoryProtocol,
)
from stacklion_api.domain.services.canonical_metric_registry import (
    get_tier1_metrics_for_statement_type,
)

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class GetFundamentalsTimeSeriesRequest:
    """Request parameters for fundamentals time-series retrieval.

    Attributes:
        ciks:
            Universe of companies expressed as CIKs. All values are stripped
            of whitespace and empty entries are discarded.
        statement_type:
            Statement type to use as the source of fundamentals (e.g.,
            INCOME_STATEMENT, BALANCE_SHEET).
        metrics:
            Optional subset of canonical metrics to include. When None, all
            metrics present in each payload's ``core_metrics`` are considered
            for that point.
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
        use_tier1_only:
            When True and ``metrics`` is None, restricts the fundamentals
            time series to the Tier-1 canonical metrics for the requested
            statement type, as defined by the canonical metric registry.
            When False (default), all metrics present in each payload's
            ``core_metrics`` are considered when ``metrics`` is None.
    """

    ciks: Sequence[str]
    statement_type: StatementType
    metrics: Sequence[CanonicalStatementMetric] | None = None
    frequency: str = "annual"
    from_date: date | None = None
    to_date: date | None = None
    use_tier1_only: bool = False


class GetFundamentalsTimeSeriesUseCase:
    """Build a fundamentals time series from normalized EDGAR statements.

    Args:
        uow: Unit-of-work used to access the EDGAR statements repository.

    Returns:
        EdgarFundamentalsTimeSeries: Domain object representing a panel-style
        time series suitable for downstream modeling.

    Raises:
        EdgarIngestionError: If required data is missing or cannot be
            retrieved.
    """

    def __init__(self, uow: UnitOfWork) -> None:
        """Initialize the use case.

        Args:
            uow: Application UnitOfWork abstraction used to resolve repositories.
        """
        self._uow = uow

    async def execute(
        self,
        req: GetFundamentalsTimeSeriesRequest,
    ) -> list[FundamentalsTimeSeriesPoint]:
        """Execute fundamentals time-series retrieval.

        Args:
            req: Parameters describing the universe and time window.

        Returns:
            Deterministically ordered list of
            :class:`FundamentalsTimeSeriesPoint` instances.

        Raises:
            EdgarMappingError:
                If the request parameters are invalid (empty universe, invalid
                frequency, or an inverted date window).
        """
        cleaned_ciks = sorted({c.strip() for c in req.ciks if c.strip()})
        if not cleaned_ciks:
            raise EdgarMappingError(
                "At least one non-empty CIK must be provided for fundamentals time series.",
            )

        from_date, to_date = self._normalize_window(req.from_date, req.to_date)

        frequency = req.frequency.lower()
        if frequency not in {"annual", "quarterly"}:
            raise EdgarMappingError(
                "Unsupported frequency for fundamentals time series; expected 'annual' or 'quarterly'.",
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
            "edgar.get_fundamentals_timeseries.start",
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

            all_payloads: list[CanonicalStatementPayload] = []

            for cik in cleaned_ciks:
                company_payloads = await self._collect_company_payloads(
                    statements_repo=statements_repo,
                    cik=cik,
                    statement_type=req.statement_type,
                    allowed_periods=allowed_periods,
                    from_date=from_date,
                    to_date=to_date,
                )
                all_payloads.extend(company_payloads)

        if req.metrics is not None:
            metric_filter: Iterable[CanonicalStatementMetric] | None = tuple(req.metrics)
        elif req.use_tier1_only:
            metric_filter = get_tier1_metrics_for_statement_type(req.statement_type)
        else:
            metric_filter = None

        series = build_fundamentals_timeseries(
            payloads=all_payloads,
            metrics=metric_filter,
        )

        logger.info(
            "edgar.get_fundamentals_timeseries.success",
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

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

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
                "from_date must be on or before to_date for fundamentals time series.",
                details={"from_date": lower.isoformat(), "to_date": upper.isoformat()},
            )

        return lower, upper

    async def _collect_company_payloads(
        self,
        *,
        statements_repo: EdgarStatementsRepositoryProtocol,
        cik: str,
        statement_type: StatementType,
        allowed_periods: set[FiscalPeriod],
        from_date: date,
        to_date: date,
    ) -> list[CanonicalStatementPayload]:
        """Collect latest normalized payloads for a single company.

        For each fiscal year in the window, this helper loads all statement
        versions via the repository and then selects, per fiscal period/date,
        the latest version (highest version_sequence) with a non-None
        normalized payload.

        Args:
            statements_repo: EDGAR statements repository.
            cik: Company CIK.
            statement_type: Statement type filter.
            allowed_periods: Fiscal periods allowed for the chosen frequency.
            from_date: Inclusive lower bound for statement_date.
            to_date: Inclusive upper bound for statement_date.

        Returns:
            List of canonical payloads for the company, one per selected
            period/version. The list is not globally sorted; callers should
            rely on `build_fundamentals_timeseries` for final ordering.
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

            # Filter down to the requested window, frequency, and only rows
            # with an attached normalized payload.
            candidates = [
                v
                for v in versions
                if v.fiscal_period in allowed_periods
                and from_date <= v.statement_date <= to_date
                and v.normalized_payload is not None
            ]

            if not candidates:
                continue

            # For each (statement_date, fiscal_period) identity, keep only
            # the latest version_sequence and its payload.
            by_key: dict[tuple[date, FiscalPeriod], CanonicalStatementPayload] = {}
            by_seq: dict[tuple[date, FiscalPeriod], int] = {}

            for v in candidates:
                key = (v.statement_date, v.fiscal_period)
                current_seq = by_seq.get(key)

                # Defensive narrowing for mypy: we already filtered on
                # normalized_payload is not None, but we narrow again here
                # to keep the type checker satisfied.
                payload = v.normalized_payload
                if payload is None:  # pragma: no cover - defensive guard
                    continue

                if current_seq is None or v.version_sequence > current_seq:
                    by_seq[key] = v.version_sequence
                    by_key[key] = payload

            payloads.extend(by_key.values())

        return payloads


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
