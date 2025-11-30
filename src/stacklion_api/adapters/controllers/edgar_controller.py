# src/stacklion_api/adapters/controllers/edgar_controller.py
# Copyright (c)
# SPDX-License-Identifier: MIT
"""EDGAR Controller.

Summary:
    Thin adapter coordinating EDGAR read-side use cases. Controllers do not
    access repositories or gateways directly; they delegate to use-cases and
    return DTOs suitable for presenters.

Design:
    * Protocol-based use-case interfaces to avoid tight coupling.
    * Simple parameter translation and validation at the controller boundary.
    * No transport concerns; HTTP-specific behavior lives in routers/presenters.

Layer:
    adapters/controllers
"""

from __future__ import annotations

from collections.abc import Sequence
from datetime import date
from typing import Any, Protocol

from stacklion_api.adapters.controllers.base import BaseController
from stacklion_api.application.schemas.dto.edgar import (
    ComputeRestatementDeltaResultDTO,
    EdgarFilingDTO,
    EdgarStatementVersionDTO,
    GetRestatementLedgerResultDTO,
    RestatementLedgerEntryDTO,
    RestatementMetricDeltaDTO,
    RestatementSummaryDTO,
)
from stacklion_api.application.schemas.dto.edgar_derived import (
    EdgarDerivedMetricsPointDTO,
)
from stacklion_api.application.use_cases.statements.compute_restatement_delta import (
    ComputeRestatementDeltaRequest,
)
from stacklion_api.application.use_cases.statements.get_derived_metrics_timeseries import (
    GetDerivedMetricsTimeSeriesRequest,
)
from stacklion_api.application.use_cases.statements.get_restatement_ledger import (
    GetRestatementLedgerRequest,
)
from stacklion_api.domain.entities.edgar_derived_timeseries import (
    DerivedMetricsTimeSeriesPoint,
)
from stacklion_api.domain.enums.derived_metric import DerivedMetric
from stacklion_api.domain.enums.edgar import FilingType, FiscalPeriod, StatementType
from stacklion_api.domain.services.metric_views import expand_view_metrics


class ListFilingsUseCase(Protocol):
    """Protocol for a use-case listing filings for a company."""

    async def execute(
        self,
        *,
        cik: str,
        filing_types: Sequence[FilingType] | None,
        from_date: date | None,
        to_date: date | None,
        include_amendments: bool,
        page: int,
        page_size: int,
    ) -> tuple[list[EdgarFilingDTO], int]:
        """Execute the list-filings use case.

        Args:
            cik: Company CIK string, typically a zero-padded identifier.
            filing_types: Optional filter for specific filing types.
            from_date: Optional lower bound on filing date (inclusive).
            to_date: Optional upper bound on filing date (inclusive).
            include_amendments: Whether to include amended filings.
            page: 1-based page index for pagination.
            page_size: Number of items per page.

        Returns:
            A tuple of (filings, total_count) for the given criteria.
        """
        ...


class GetFilingUseCase(Protocol):
    """Protocol for a use-case retrieving a single filing."""

    async def execute(
        self,
        *,
        cik: str,
        accession_id: str,
    ) -> EdgarFilingDTO:
        """Execute the get-filing use case.

        Args:
            cik: Company CIK string.
            accession_id: Filing accession identifier.

        Returns:
            The matching filing DTO.

        Raises:
            Domain-level exceptions if the filing cannot be resolved.
        """
        ...


class ListStatementVersionsUseCase(Protocol):
    """Protocol for a use-case listing statement versions for a company."""

    async def execute(
        self,
        *,
        cik: str,
        statement_type: StatementType,
        from_date: date | None,
        to_date: date | None,
        include_restated: bool,
        page: int,
        page_size: int,
    ) -> tuple[list[EdgarStatementVersionDTO], int]:
        """Execute the list-statement-versions use case.

        Args:
            cik: Company CIK string.
            statement_type: Type of financial statement to filter on.
            from_date: Optional lower bound on statement_date (inclusive).
            to_date: Optional upper bound on statement_date (inclusive).
            include_restated: Whether restated versions should be included.
            page: 1-based page index.
            page_size: Number of items per page.

        Returns:
            A tuple of (statement_versions, total_count).
        """
        ...


class GetStatementVersionsForFilingUseCase(Protocol):
    """Protocol for a use-case retrieving statement versions for a filing."""

    async def execute(
        self,
        *,
        cik: str,
        accession_id: str,
        statement_type: StatementType | None,
        include_restated: bool,
        include_normalized: bool,
    ) -> tuple[EdgarFilingDTO, list[EdgarStatementVersionDTO]]:
        """Execute the get-statement-versions-for-filing use case.

        Args:
            cik: Company CIK string.
            accession_id: Filing accession identifier.
            statement_type: Optional filter for statement type.
            include_restated: Whether to include restated statement versions.
            include_normalized: Whether normalized payloads should be requested.

        Returns:
            A tuple of (filing_dto, statement_versions) for the filing.
        """
        ...


class GetDerivedMetricsTimeSeriesUseCase(Protocol):
    """Protocol for a use-case building derived metrics time series."""

    async def execute(
        self,
        req: GetDerivedMetricsTimeSeriesRequest,
    ) -> list[DerivedMetricsTimeSeriesPoint]:
        """Execute the derived-metrics time-series use case.

        Args:
            req: Parameter object describing the universe and window.

        Returns:
            List of domain-level derived metrics time-series points.
        """
        ...


class ComputeRestatementDeltaUseCase(Protocol):
    """Protocol for the restatement delta use case."""

    async def execute(
        self,
        req: ComputeRestatementDeltaRequest,
    ) -> Any:
        """Execute the restatement delta use case.

        The concrete result type is a domain object with at least:

            - ``delta.metrics``: mapping from canonical metric enums to
              metric-delta objects exposing ``old``, ``new``, and ``diff``
              attributes.

        This controller maps that domain result into DTOs.
        """
        ...


class GetRestatementLedgerUseCase(Protocol):
    """Protocol for the restatement ledger use case."""

    async def execute(
        self,
        req: GetRestatementLedgerRequest,
    ) -> Any:
        """Execute the restatement ledger use case.

        The concrete result type is a domain object with at least:

            - ``cik``, ``statement_type``, ``fiscal_year``, ``fiscal_period``.
            - ``entries``: iterable of entry objects exposing:
                * ``from_version_sequence``
                * ``to_version_sequence``
                * ``summary`` with the same shape as RestatementSummaryDTO.
                * optionally ``delta.metrics`` for per-metric deltas.
        """
        ...


class EdgarController(BaseController):
    """Controller orchestrating EDGAR filings, statements, and derived metrics."""

    def __init__(
        self,
        list_filings_uc: ListFilingsUseCase,
        get_filing_uc: GetFilingUseCase,
        list_statements_uc: ListStatementVersionsUseCase,
        get_filing_statements_uc: GetStatementVersionsForFilingUseCase,
        get_derived_metrics_timeseries_uc: GetDerivedMetricsTimeSeriesUseCase | None = None,
        compute_restatement_delta_uc: ComputeRestatementDeltaUseCase | None = None,
        get_restatement_ledger_uc: GetRestatementLedgerUseCase | None = None,
    ) -> None:
        """Initialize the controller with its use-cases.

        Args:
            list_filings_uc: Use-case responsible for listing filings.
            get_filing_uc: Use-case responsible for retrieving a single filing.
            list_statements_uc: Use-case listing statement versions.
            get_filing_statements_uc: Use-case retrieving versions for a filing.
            get_derived_metrics_timeseries_uc:
                Optional use-case building derived metrics time-series points.
                May be None in legacy wiring or tests that do not exercise
                derived metrics behavior.
            compute_restatement_delta_uc:
                Optional use-case computing restatement deltas between two
                statement versions.
            get_restatement_ledger_uc:
                Optional use-case producing a restatement ledger across a
                statement's version history.
        """
        self._list_filings_uc = list_filings_uc
        self._get_filing_uc = get_filing_uc
        self._list_statements_uc = list_statements_uc
        self._get_filing_statements_uc = get_filing_statements_uc
        self._get_derived_metrics_timeseries_uc = get_derived_metrics_timeseries_uc
        self._compute_restatement_delta_uc = compute_restatement_delta_uc
        self._get_restatement_ledger_uc = get_restatement_ledger_uc

    # ------------------------------------------------------------------
    # Filings
    # ------------------------------------------------------------------

    async def list_filings(
        self,
        *,
        cik: str,
        filing_types: Sequence[FilingType] | None,
        from_date: date | None,
        to_date: date | None,
        include_amendments: bool,
        page: int,
        page_size: int,
    ) -> tuple[list[EdgarFilingDTO], int]:
        """List filings for a company.

        Args:
            cik: Company CIK.
            filing_types: Optional filter for filing types.
            from_date: Optional lower bound on filing date (inclusive).
            to_date: Optional upper bound on filing date (inclusive).
            include_amendments: Whether to include amendments.
            page: 1-based page index.
            page_size: Items per page.

        Returns:
            Tuple of (filings, total_count).
        """
        return await self._list_filings_uc.execute(
            cik=cik.strip(),
            filing_types=filing_types,
            from_date=from_date,
            to_date=to_date,
            include_amendments=include_amendments,
            page=page,
            page_size=page_size,
        )

    async def get_filing(
        self,
        *,
        cik: str,
        accession_id: str,
    ) -> EdgarFilingDTO:
        """Retrieve a single filing for a company.

        Args:
            cik: Company CIK.
            accession_id: Filing accession identifier.

        Returns:
            Filing DTO.

        Raises:
            Domain-specific exceptions if the filing does not exist or cannot
            be resolved; routers map these to HTTP errors.
        """
        return await self._get_filing_uc.execute(
            cik=cik.strip(),
            accession_id=accession_id.strip(),
        )

    # ------------------------------------------------------------------
    # Statement versions
    # ------------------------------------------------------------------

    async def list_statements(
        self,
        *,
        cik: str,
        statement_type: StatementType,
        from_date: date | None,
        to_date: date | None,
        include_restated: bool,
        page: int,
        page_size: int,
    ) -> tuple[list[EdgarStatementVersionDTO], int]:
        """List statement versions for a company.

        Args:
            cik: Company CIK.
            statement_type: Statement type filter (e.g., income statement).
            from_date: Optional lower bound on statement_date (inclusive).
            to_date: Optional upper bound on statement_date (inclusive).
            include_restated: Whether to include restated versions.
            page: 1-based page index.
            page_size: Items per page.

        Returns:
            Tuple of (statement_versions, total_count).
        """
        return await self._list_statements_uc.execute(
            cik=cik.strip(),
            statement_type=statement_type,
            from_date=from_date,
            to_date=to_date,
            include_restated=include_restated,
            page=page,
            page_size=page_size,
        )

    async def get_statement_versions_for_filing(
        self,
        *,
        cik: str,
        accession_id: str,
        statement_type: StatementType | None,
        include_restated: bool,
        include_normalized: bool,
    ) -> tuple[EdgarFilingDTO, list[EdgarStatementVersionDTO]]:
        """Retrieve statement versions associated with a specific filing.

        Args:
            cik: Company CIK.
            accession_id: Filing accession identifier.
            statement_type: Optional filter for statement type.
            include_restated: Whether to include restated versions.
            include_normalized: Whether normalized payloads were requested.

        Returns:
            Tuple of (filing_dto, statement_versions).

        Notes:
            Normalized payloads are not yet populated in E5. The use-case may
            ignore ``include_normalized`` for now while still accepting it.
        """
        return await self._get_filing_statements_uc.execute(
            cik=cik.strip(),
            accession_id=accession_id.strip(),
            statement_type=statement_type,
            include_restated=include_restated,
            include_normalized=include_normalized,
        )

    # ------------------------------------------------------------------
    # Derived metrics time series
    # ------------------------------------------------------------------

    async def get_derived_metrics_timeseries(
        self,
        *,
        ciks: Sequence[str],
        statement_type: StatementType,
        metrics: Sequence[DerivedMetric] | None,
        frequency: str,
        from_date: date | None,
        to_date: date | None,
        bundle_code: str | None = None,
    ) -> list[EdgarDerivedMetricsPointDTO]:
        """Build a derived metrics time series for a universe of companies.

        Args:
            ciks:
                Universe of company CIKs.
            statement_type:
                Source statement type for fundamentals.
            metrics:
                Optional subset of derived metrics to include. When omitted and
                ``bundle_code`` is also None, the use-case may choose a default
                metric set (e.g., all registered metrics).
            frequency:
                Time-series frequency ("annual" or "quarterly").
            from_date:
                Optional inclusive lower bound on statement_date.
            to_date:
                Optional inclusive upper bound on statement_date.
            bundle_code:
                Optional metric-view code selecting a predefined bundle of
                derived metrics (e.g., "core_fundamentals"). When provided,
                explicit ``metrics`` must be omitted.

        Returns:
            List of derived metrics time-series DTOs, suitable for HTTP
            presenters. Metric values are converted to string representations
            for wire stability.

        Raises:
            RuntimeError:
                If the derived metrics time-series use case has not been wired.
            ValueError:
                If ``bundle_code`` is unknown or provided together with
                explicit ``metrics``.
        """
        if self._get_derived_metrics_timeseries_uc is None:
            raise RuntimeError(
                "Derived metrics time-series use case is not wired on EdgarController.",
            )

        cleaned_ciks = [c.strip() for c in ciks if c.strip()]
        normalized_bundle = bundle_code.strip() if bundle_code is not None else None

        if metrics is not None and normalized_bundle is not None:
            raise ValueError("bundle_code and metrics cannot both be provided.")

        effective_metrics: Sequence[DerivedMetric] | None = metrics

        if normalized_bundle is not None:
            # Delegate bundle resolution to the domain registry. This raises
            # ValueError("Unknown metric view: <code>") for unknown bundles.
            try:
                metrics_from_view = expand_view_metrics(normalized_bundle)
            except ValueError as exc:
                raise ValueError(str(exc)) from exc
            effective_metrics = list(metrics_from_view)

        req = GetDerivedMetricsTimeSeriesRequest(
            ciks=cleaned_ciks,
            statement_type=statement_type,
            metrics=effective_metrics,
            frequency=frequency,
            from_date=from_date,
            to_date=to_date,
        )

        series: list[DerivedMetricsTimeSeriesPoint] = (
            await self._get_derived_metrics_timeseries_uc.execute(req)
        )

        # Adapter boundary: map domain points → DTOs and stringify metric values.
        dtos = [
            EdgarDerivedMetricsPointDTO(
                cik=point.cik,
                statement_type=point.statement_type,
                accounting_standard=point.accounting_standard,
                statement_date=point.statement_date,
                fiscal_year=point.fiscal_year,
                fiscal_period=point.fiscal_period,
                currency=point.currency,
                metrics={metric: str(value) for metric, value in point.metrics.items()},
                normalized_payload_version_sequence=point.normalized_payload_version_sequence,
            )
            for point in series
        ]

        return dtos

    # ------------------------------------------------------------------
    # Restatements: delta
    # ------------------------------------------------------------------

    async def compute_restatement_delta(
        self,
        *,
        cik: str,
        statement_type: StatementType,
        fiscal_year: int,
        fiscal_period: FiscalPeriod,
        from_version_sequence: int,
        to_version_sequence: int,
    ) -> ComputeRestatementDeltaResultDTO:
        """Compute a restatement delta between two statement versions.

        This is a thin adapter over the domain restatement-delta use case. It
        maps the domain result into a transport-ready DTO structure with
        stringified numeric values and canonical metric codes.
        """
        if self._compute_restatement_delta_uc is None:
            raise RuntimeError(
                "ComputeRestatementDeltaUseCase is not wired on EdgarController.",
            )

        req = ComputeRestatementDeltaRequest(
            cik=cik.strip(),
            statement_type=statement_type,
            fiscal_year=fiscal_year,
            fiscal_period=fiscal_period,
            from_version_sequence=from_version_sequence,
            to_version_sequence=to_version_sequence,
            metrics=None,
        )

        result: Any = await self._compute_restatement_delta_uc.execute(req)

        # Domain contract: result.delta.metrics is a mapping from canonical
        # metric enum → metric delta object with old/new/diff attributes.
        delta_obj: Any = getattr(result, "delta", None)
        metrics_map: dict[Any, Any] = getattr(delta_obj, "metrics", {}) if delta_obj else {}

        deltas: list[RestatementMetricDeltaDTO] = []
        for metric_key, metric_delta in metrics_map.items():
            metric_code = getattr(metric_key, "value", str(metric_key))

            old_val = getattr(metric_delta, "old", None)
            new_val = getattr(metric_delta, "new", None)
            diff_val = getattr(metric_delta, "diff", None)

            deltas.append(
                RestatementMetricDeltaDTO(
                    metric=metric_code,
                    old_value=str(old_val) if old_val is not None else None,
                    new_value=str(new_val) if new_val is not None else None,
                    diff=str(diff_val) if diff_val is not None else None,
                ),
            )

        total_metrics_compared = len(metrics_map)
        total_metrics_changed = sum(
            1
            for metric_delta in metrics_map.values()
            if getattr(metric_delta, "diff", None) not in (None, 0)
        )
        summary = RestatementSummaryDTO(
            total_metrics_compared=total_metrics_compared,
            total_metrics_changed=total_metrics_changed,
            has_material_change=total_metrics_changed > 0,
        )

        return ComputeRestatementDeltaResultDTO(
            cik=cik.strip(),
            statement_type=statement_type,
            fiscal_year=fiscal_year,
            fiscal_period=fiscal_period,
            from_version_sequence=from_version_sequence,
            to_version_sequence=to_version_sequence,
            summary=summary,
            deltas=deltas,
        )

    # ------------------------------------------------------------------
    # Restatements: ledger
    # ------------------------------------------------------------------

    async def get_restatement_ledger(
        self,
        *,
        cik: str,
        statement_type: StatementType,
        fiscal_year: int,
        fiscal_period: FiscalPeriod,
    ) -> GetRestatementLedgerResultDTO:
        """Build a restatement ledger across statement versions.

        The ledger is an ordered sequence of hops between adjacent versions,
        each with a summary and optional per-metric deltas.
        """
        if self._get_restatement_ledger_uc is None:
            raise RuntimeError(
                "GetRestatementLedgerUseCase is not wired on EdgarController.",
            )

        req = GetRestatementLedgerRequest(
            cik=cik.strip(),
            statement_type=statement_type,
            fiscal_year=fiscal_year,
            fiscal_period=fiscal_period,
        )

        result: Any = await self._get_restatement_ledger_uc.execute(req)

        entries_dto: list[RestatementLedgerEntryDTO] = []
        for entry in getattr(result, "entries", []):
            summary_domain: Any = getattr(entry, "summary", None)
            if summary_domain is not None:
                summary_dto = RestatementSummaryDTO(
                    total_metrics_compared=getattr(
                        summary_domain,
                        "total_metrics_compared",
                        0,
                    ),
                    total_metrics_changed=getattr(
                        summary_domain,
                        "total_metrics_changed",
                        0,
                    ),
                    has_material_change=bool(
                        getattr(summary_domain, "has_material_change", False),
                    ),
                )
            else:
                summary_dto = RestatementSummaryDTO(
                    total_metrics_compared=0,
                    total_metrics_changed=0,
                    has_material_change=False,
                )

            # Optional metric deltas per hop, if the domain exposes them.
            delta_obj: Any = getattr(entry, "delta", None)
            metrics_map: dict[Any, Any] = getattr(delta_obj, "metrics", {}) if delta_obj else {}

            metric_deltas_dto: list[RestatementMetricDeltaDTO] = []
            for metric_key, metric_delta in metrics_map.items():
                metric_code = getattr(metric_key, "value", str(metric_key))

                old_val = getattr(metric_delta, "old", None)
                new_val = getattr(metric_delta, "new", None)
                diff_val = getattr(metric_delta, "diff", None)

                metric_deltas_dto.append(
                    RestatementMetricDeltaDTO(
                        metric=metric_code,
                        old_value=str(old_val) if old_val is not None else None,
                        new_value=str(new_val) if new_val is not None else None,
                        diff=str(diff_val) if diff_val is not None else None,
                    ),
                )

            entries_dto.append(
                RestatementLedgerEntryDTO(
                    from_version_sequence=entry.from_version_sequence,
                    to_version_sequence=entry.to_version_sequence,
                    summary=summary_dto,
                    deltas=metric_deltas_dto,
                ),
            )

        return GetRestatementLedgerResultDTO(
            cik=cik.strip(),
            statement_type=statement_type,
            fiscal_year=fiscal_year,
            fiscal_period=fiscal_period,
            entries=entries_dto,
        )
