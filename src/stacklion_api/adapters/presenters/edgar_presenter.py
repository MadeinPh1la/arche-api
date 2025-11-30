# Copyright (c) Stacklion.
# SPDX-License-Identifier: MIT
"""Presenter: EDGAR filings and statements → HTTP envelopes.

Purpose:
    Map EDGAR application-layer DTOs into canonical HTTP schemas and envelopes:

        * PaginatedEnvelope[EdgarFilingHTTP]
        * PaginatedEnvelope[EdgarStatementVersionSummaryHTTP]
        * SuccessEnvelope[EdgarFilingHTTP]
        * SuccessEnvelope[EdgarStatementVersionListHTTP]
        * SuccessEnvelope[EdgarDerivedMetricsTimeSeriesHTTP]
        * SuccessEnvelope[MetricViewsCatalogHTTP]

Design:
    * Never leaks DB or internal shapes.
    * Enforces deterministic sorting of collections.
    * Uses BasePresenter helpers for envelopes and headers.
    * Emits structured logs for observability.

Layer:
    adapters/presenters
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from datetime import date
from typing import Any

from stacklion_api.adapters.presenters.base_presenter import (
    BasePresenter,
    PresentResult,
)
from stacklion_api.adapters.schemas.http.edgar_schemas import (
    EdgarDerivedMetricsPointHTTP,
    EdgarDerivedMetricsTimeSeriesHTTP,
    EdgarFilingHTTP,
    EdgarStatementVersionHTTP,
    EdgarStatementVersionListHTTP,
    EdgarStatementVersionSummaryHTTP,
    MetricViewHTTP,
    MetricViewsCatalogHTTP,
    NormalizedStatementHTTP,
)
from stacklion_api.adapters.schemas.http.envelopes import (
    PaginatedEnvelope,
    SuccessEnvelope,
)
from stacklion_api.application.schemas.dto.edgar import (
    EdgarFilingDTO,
    EdgarStatementVersionDTO,
)
from stacklion_api.application.schemas.dto.edgar_derived import EdgarDerivedMetricsPointDTO
from stacklion_api.domain.enums.edgar import StatementType
from stacklion_api.domain.services.metric_views import MetricView
from stacklion_api.infrastructure.logging.logger import get_json_logger

_LOGGER = get_json_logger(__name__)


class EdgarPresenter(BasePresenter[SuccessEnvelope[Any]]):
    """Presenter for EDGAR HTTP responses.

    This presenter provides mapping helpers from application DTOs to HTTP
    schemas and envelopes. Business logic remains in use-cases; the presenter
    only shapes data and headers.
    """

    # ------------------------------------------------------------------
    # Filings
    # ------------------------------------------------------------------

    @staticmethod
    def _map_filing_dto(dto: EdgarFilingDTO) -> EdgarFilingHTTP:
        """Map an application-layer filing DTO to the HTTP schema.

        Args:
            dto: Application DTO representing a filing.

        Returns:
            EdgarFilingHTTP: HTTP-facing schema instance.
        """
        return EdgarFilingHTTP(
            accession_id=dto.accession_id,
            cik=dto.cik,
            company_name=dto.company_name,
            filing_type=dto.filing_type,
            filing_date=dto.filing_date,
            period_end_date=dto.period_end_date,
            is_amendment=dto.is_amendment,
            amendment_sequence=dto.amendment_sequence,
            primary_document=dto.primary_document,
            accepted_at=dto.accepted_at,
        )

    def present_filings_page(
        self,
        *,
        dtos: list[EdgarFilingDTO],
        page: int,
        page_size: int,
        total: int,
        trace_id: str | None = None,
    ) -> PresentResult[PaginatedEnvelope[EdgarFilingHTTP]]:
        """Present a paginated page of filings.

        The collection is sorted deterministically by:

            * filing_date DESC
            * accession_id DESC

        Args:
            dtos: Filing DTOs for the current page.
            page: 1-based page index.
            page_size: Number of items per page.
            total: Total number of matching filings.
            trace_id: Optional request correlation identifier.

        Returns:
            PresentResult containing a PaginatedEnvelope of EdgarFilingHTTP.
        """
        # Sort defensively, even if upstream has already sorted.
        sorted_dtos = sorted(
            dtos,
            key=lambda f: (f.filing_date, f.accession_id),
            reverse=True,
        )
        items = [self._map_filing_dto(dto) for dto in sorted_dtos]

        _LOGGER.info(
            "edgar_presenter_filings_page",
            extra={
                "trace_id": trace_id,
                "page": page,
                "page_size": page_size,
                "total": total,
                "items": len(items),
            },
        )

        return self.present_paginated(
            items=items,
            page=page,
            page_size=page_size,
            total=total,
            trace_id=trace_id,
            etag=None,
        )

    def present_filing_detail(
        self,
        *,
        dto: EdgarFilingDTO,
        trace_id: str | None = None,
    ) -> PresentResult[SuccessEnvelope[EdgarFilingHTTP]]:
        """Present a single filing as SuccessEnvelope[EdgarFilingHTTP].

        Args:
            dto: Filing DTO to present.
            trace_id: Optional request correlation identifier.

        Returns:
            PresentResult containing SuccessEnvelope[EdgarFilingHTTP].
        """
        payload = self._map_filing_dto(dto)
        _LOGGER.info(
            "edgar_presenter_filing_detail",
            extra={"trace_id": trace_id, "accession_id": dto.accession_id, "cik": dto.cik},
        )
        return self.present_success(data=payload, trace_id=trace_id)

    # ------------------------------------------------------------------
    # Statement versions
    # ------------------------------------------------------------------

    @staticmethod
    def _map_statement_dto_to_summary(
        dto: EdgarStatementVersionDTO,
    ) -> EdgarStatementVersionSummaryHTTP:
        """Map a statement version DTO to its HTTP summary representation.

        Args:
            dto: Statement version DTO.

        Returns:
            EdgarStatementVersionSummaryHTTP: HTTP-facing summary schema.
        """
        return EdgarStatementVersionSummaryHTTP(
            accession_id=dto.accession_id,
            cik=dto.cik,
            company_name=dto.company_name,
            statement_type=dto.statement_type,
            accounting_standard=dto.accounting_standard,
            statement_date=dto.statement_date,
            fiscal_year=dto.fiscal_year,
            fiscal_period=dto.fiscal_period,
            currency=dto.currency,
            is_restated=dto.is_restated,
            restatement_reason=dto.restatement_reason,
            version_source=dto.version_source,
            version_sequence=dto.version_sequence,
            filing_type=dto.filing_type,
            filing_date=dto.filing_date,
        )

    @staticmethod
    def _map_statement_dto_to_full(
        dto: EdgarStatementVersionDTO,
        normalized_payload: NormalizedStatementHTTP | None,
    ) -> EdgarStatementVersionHTTP:
        """Map a statement version DTO to the full HTTP schema.

        Args:
            dto: Statement version DTO.
            normalized_payload: Optional normalized payload; currently None.

        Returns:
            EdgarStatementVersionHTTP: HTTP-facing full schema.
        """
        return EdgarStatementVersionHTTP(
            accession_id=dto.accession_id,
            cik=dto.cik,
            company_name=dto.company_name,
            statement_type=dto.statement_type,
            accounting_standard=dto.accounting_standard,
            statement_date=dto.statement_date,
            fiscal_year=dto.fiscal_year,
            fiscal_period=dto.fiscal_period,
            currency=dto.currency,
            is_restated=dto.is_restated,
            restatement_reason=dto.restatement_reason,
            version_source=dto.version_source,
            version_sequence=dto.version_sequence,
            filing_type=dto.filing_type,
            filing_date=dto.filing_date,
            normalized_payload=normalized_payload,
        )

    def present_statement_versions_page(
        self,
        *,
        dtos: list[EdgarStatementVersionDTO],
        page: int,
        page_size: int,
        total: int,
        trace_id: str | None = None,
    ) -> PresentResult[PaginatedEnvelope[EdgarStatementVersionSummaryHTTP]]:
        """Present a paginated page of statement version summaries.

        The collection is sorted deterministically by:

            * statement_date DESC
            * version_sequence DESC

        Args:
            dtos: Statement version DTOs for the current page.
            page: 1-based page index.
            page_size: Number of items per page.
            total: Total number of matching statement versions.
            trace_id: Optional request correlation identifier.

        Returns:
            PresentResult containing PaginatedEnvelope[EdgarStatementVersionSummaryHTTP].
        """
        sorted_dtos = sorted(
            dtos,
            key=lambda s: (s.statement_date, s.version_sequence),
            reverse=True,
        )
        items = [self._map_statement_dto_to_summary(dto) for dto in sorted_dtos]

        _LOGGER.info(
            "edgar_presenter_statement_versions_page",
            extra={
                "trace_id": trace_id,
                "page": page,
                "page_size": page_size,
                "total": total,
                "items": len(items),
            },
        )

        return self.present_paginated(
            items=items,
            page=page,
            page_size=page_size,
            total=total,
            trace_id=trace_id,
            etag=None,
        )

    def present_statement_versions_for_filing(
        self,
        *,
        filing: EdgarFilingDTO,
        versions: Iterable[EdgarStatementVersionDTO],
        include_normalized: bool,
        trace_id: str | None = None,
    ) -> PresentResult[SuccessEnvelope[EdgarStatementVersionListHTTP]]:
        """Present statement versions associated with a single filing.

        Note:
            ``include_normalized`` is accepted for contract stability but not
            acted on in this phase. ``normalized_payload`` is always None.

        Args:
            filing: Filing DTO associated with the statement versions.
            versions: Iterable of statement version DTOs.
            include_normalized: Whether the caller requested normalized payload.
            trace_id: Optional request correlation identifier.

        Returns:
            PresentResult containing SuccessEnvelope[EdgarStatementVersionListHTTP].
        """
        filing_http = self._map_filing_dto(filing)

        # Apply deterministic ordering before mapping.
        sorted_versions = sorted(
            versions,
            key=lambda s: (s.statement_date, s.version_sequence),
            reverse=True,
        )

        items = [
            self._map_statement_dto_to_full(
                dto=v,
                normalized_payload=None,  # Future work; contract reserved.
            )
            for v in sorted_versions
        ]

        payload = EdgarStatementVersionListHTTP(filing=filing_http, items=items)

        _LOGGER.info(
            "edgar_presenter_statement_versions_for_filing",
            extra={
                "trace_id": trace_id,
                "accession_id": filing.accession_id,
                "cik": filing.cik,
                "versions_count": len(items),
                "include_normalized": include_normalized,
            },
        )

        return self.present_success(data=payload, trace_id=trace_id)

    # ------------------------------------------------------------------
    # Derived metrics time series
    # ------------------------------------------------------------------

    @staticmethod
    def _map_derived_point_dto(
        dto: EdgarDerivedMetricsPointDTO,
    ) -> EdgarDerivedMetricsPointHTTP:
        """Map a derived metrics DTO to the HTTP schema.

        Args:
            dto: Application-layer derived metrics point DTO.

        Returns:
            EdgarDerivedMetricsPointHTTP: HTTP-facing schema instance.
        """
        return EdgarDerivedMetricsPointHTTP(
            cik=dto.cik,
            statement_type=dto.statement_type,
            accounting_standard=dto.accounting_standard,
            statement_date=dto.statement_date,
            fiscal_year=dto.fiscal_year,
            fiscal_period=dto.fiscal_period,
            currency=dto.currency,
            # Expose metric codes as strings on the wire.
            metrics={metric.value: value for metric, value in dto.metrics.items()},
            normalized_payload_version_sequence=dto.normalized_payload_version_sequence,
        )

    def present_derived_timeseries(
        self,
        *,
        dtos: list[EdgarDerivedMetricsPointDTO],
        ciks: list[str] | None = None,
        statement_type: StatementType | None = None,
        frequency: str | None = None,
        from_date: date | None = None,
        to_date: date | None = None,
        trace_id: str | None = None,
        view: str | None = None,
    ) -> PresentResult[SuccessEnvelope[EdgarDerivedMetricsTimeSeriesHTTP]]:
        """Present a derived metrics time series.

        The collection is sorted deterministically by:

            * cik (ascending)
            * statement_date (ascending)
            * fiscal_period value (ascending)
            * normalized_payload_version_sequence (ascending)

        Args:
            dtos:
                Derived metrics DTOs to present.
            ciks:
                Optional explicit universe of requested CIKs. When omitted, the
                universe is inferred from the DTOs.
            statement_type:
                Statement type used as the base for derived metrics. When
                omitted, inferred from the first DTO (if any).
            frequency:
                Time-series frequency ("annual" or "quarterly"). When omitted,
                defaults to "annual".
            from_date:
                Inclusive lower bound on statement_date. When omitted, inferred
                as the minimum statement_date across DTOs (or today if empty).
            to_date:
                Inclusive upper bound on statement_date. When omitted, inferred
                as the maximum statement_date across DTOs (or equal to
                from_date if empty).
            trace_id:
                Optional request correlation identifier.
            view:
                Optional metric view (bundle) identifier when the series is
                produced via a named view. Null for ad-hoc selections.

        Returns:
            PresentResult containing SuccessEnvelope[EdgarDerivedMetricsTimeSeriesHTTP].
        """
        # Deterministic ordering of individual points.
        sorted_dtos = sorted(
            dtos,
            key=lambda p: (
                p.cik,
                p.statement_date,
                p.fiscal_period.value,
                p.normalized_payload_version_sequence,
            ),
        )
        points = [self._map_derived_point_dto(dto) for dto in sorted_dtos]

        # Resolve CIK universe.
        if ciks is not None:
            normalized_ciks = sorted({c.strip() for c in ciks if c.strip()})
        else:
            normalized_ciks = sorted({p.cik for p in dtos})

        # Resolve statement_type.
        if statement_type is not None:
            resolved_statement_type = statement_type
        elif dtos:
            resolved_statement_type = dtos[0].statement_type
        else:
            # Defensive default; in practice an empty series is unusual.
            resolved_statement_type = StatementType.INCOME_STATEMENT

        # Resolve frequency.
        resolved_frequency = (frequency or "annual").lower()

        # Resolve date window.
        if from_date is not None:
            resolved_from_date = from_date
        elif dtos:
            resolved_from_date = min(p.statement_date for p in dtos)
        else:
            resolved_from_date = date.today()

        if to_date is not None:
            resolved_to_date = to_date
        elif dtos:
            resolved_to_date = max(p.statement_date for p in dtos)
        else:
            resolved_to_date = resolved_from_date

        payload = EdgarDerivedMetricsTimeSeriesHTTP(
            ciks=normalized_ciks,
            statement_type=resolved_statement_type,
            frequency=resolved_frequency,
            from_date=resolved_from_date,
            to_date=resolved_to_date,
            points=points,
            view=view,
        )

        _LOGGER.info(
            "edgar_presenter_derived_timeseries",
            extra={
                "trace_id": trace_id,
                "ciks": normalized_ciks,
                "statement_type": resolved_statement_type.value,
                "frequency": resolved_frequency,
                "from_date": resolved_from_date.isoformat(),
                "to_date": resolved_to_date.isoformat(),
                "points": len(points),
                "view": view,
            },
        )

        return self.present_success(data=payload, trace_id=trace_id)

    # ------------------------------------------------------------------
    # Metric views catalog
    # ------------------------------------------------------------------

    def present_metric_views_catalog(
        self,
        *,
        views: Iterable[MetricView],
        trace_id: str | None = None,
    ) -> PresentResult[SuccessEnvelope[MetricViewsCatalogHTTP]]:
        """Present the catalog of registered metric views.

        Args:
            views:
                Iterable of domain metric views.
            trace_id:
                Optional request correlation identifier.

        Returns:
            PresentResult containing SuccessEnvelope[MetricViewsCatalogHTTP].
        """
        sorted_views = sorted(views, key=lambda v: v.code)
        items = [
            MetricViewHTTP(
                code=v.code,
                label=v.label,
                description=v.description,
                metrics=[m.value for m in v.metrics],
            )
            for v in sorted_views
        ]

        payload = MetricViewsCatalogHTTP(views=items)

        _LOGGER.info(
            "edgar_presenter_metric_views_catalog",
            extra={
                "trace_id": trace_id,
                "views_count": len(items),
                "view_codes": [v.code for v in sorted_views],
            },
        )

        return self.present_success(data=payload, trace_id=trace_id)

    # ------------------------------------------------------------------
    # Error facade (optional convenience)
    # ------------------------------------------------------------------

    def present_domain_error(
        self,
        *,
        code: str,
        http_status: int,
        message: str,
        trace_id: str | None,
        details: Mapping[str, Any] | None = None,
    ) -> PresentResult[Any]:
        """Convenience wrapper for error presentation.

        Routers may choose to use this helper instead of assembling error
        envelopes manually.

        Args:
            code: Stable machine-readable error code.
            http_status: HTTP status for the error.
            message: Human-readable message.
            trace_id: Optional request correlation identifier.
            details: Optional structured details.

        Returns:
            PresentResult containing an ErrorEnvelope.
        """
        return self.present_error(
            code=code,
            http_status=http_status,
            message=message,
            trace_id=trace_id,
            details=dict(details or {}),
        )
