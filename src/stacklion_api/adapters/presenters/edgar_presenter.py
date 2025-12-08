# src/stacklion_api/adapters/presenters/edgar_presenter.py
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
        * SuccessEnvelope[EdgarDerivedMetricsCatalogHTTP]
        * RestatementDeltaSuccessEnvelope
        * SuccessEnvelope[RestatementLedgerHTTP]
        * SuccessEnvelope[RestatementMetricTimelineHTTP]

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
    DQAnomalyHTTP,
    EdgarDerivedMetricsCatalogHTTP,
    EdgarDerivedMetricSpecHTTP,
    EdgarDerivedMetricsPointHTTP,
    EdgarDerivedMetricsTimeSeriesHTTP,
    EdgarFilingHTTP,
    EdgarStatementVersionHTTP,
    EdgarStatementVersionListHTTP,
    EdgarStatementVersionSummaryHTTP,
    FactQualityHTTP,
    MetricViewHTTP,
    MetricViewsCatalogHTTP,
    NormalizedFactHTTP,
    NormalizedStatementHTTP,
    PersistNormalizedFactsResultHTTP,
    RestatementDeltaHTTP,
    RestatementLedgerEntryHTTP,
    RestatementLedgerHTTP,
    RestatementMetricDeltaHTTP,
    RestatementMetricTimelineHTTP,
    RestatementSummaryHTTP,
    RunStatementDQResultHTTP,
    StatementDQOverlayHTTP,
)
from stacklion_api.adapters.schemas.http.envelopes import (
    PaginatedEnvelope,
    RestatementDeltaSuccessEnvelope,
    SuccessEnvelope,
)
from stacklion_api.application.schemas.dto.edgar import (
    ComputeRestatementDeltaResultDTO,
    EdgarFilingDTO,
    EdgarStatementVersionDTO,
    GetRestatementLedgerResultDTO,
    NormalizedStatementPayloadDTO,
    RestatementLedgerEntryDTO,
    RestatementMetricDeltaDTO,
    RestatementMetricTimelineDTO,
    RestatementSummaryDTO,
)
from stacklion_api.application.schemas.dto.edgar_derived import EdgarDerivedMetricsPointDTO
from stacklion_api.application.schemas.dto.edgar_dq import (
    DQAnomalyDTO,
    FactQualityDTO,
    NormalizedFactDTO,
    PersistNormalizedFactsResultDTO,
    RunStatementDQResultDTO,
    StatementDQOverlayDTO,
)
from stacklion_api.domain.enums.edgar import StatementType
from stacklion_api.domain.services.derived_metrics_engine import DerivedMetricSpec
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
    def _map_normalized_payload_dto_to_http(
        dto: NormalizedStatementPayloadDTO,
    ) -> NormalizedStatementHTTP:
        """Map a NormalizedStatementPayloadDTO into the HTTP schema.

        Args:
            dto: Application-layer normalized statement payload DTO.

        Returns:
            NormalizedStatementHTTP: HTTP-facing normalized payload schema.
        """
        # HTTP schema exposes a flattened metrics map; internal DTO keeps
        # core/extra split. Merge them for the wire contract.
        merged_metrics: dict[str, str] = {}
        merged_metrics.update(dto.core_metrics)
        merged_metrics.update(dto.extra_metrics)

        return NormalizedStatementHTTP(
            cik=dto.cik,
            statement_type=dto.statement_type,
            accounting_standard=dto.accounting_standard,
            statement_date=dto.statement_date,
            fiscal_year=dto.fiscal_year,
            fiscal_period=dto.fiscal_period,
            currency=dto.currency,
            unit_multiplier=dto.unit_multiplier,
            source_accession_id=dto.source_accession_id,
            source_taxonomy=dto.source_taxonomy,
            source_version_sequence=dto.source_version_sequence,
        )

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
            version_sequence=dto.version_sequence,
            version_source=dto.version_source,
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
            normalized_payload:
                Optional pre-mapped normalized payload. When None, the DTO's
                `normalized_payload` field (if present) will be used.

        Returns:
            EdgarStatementVersionHTTP: HTTP-facing full schema.
        """
        effective_payload = normalized_payload
        if effective_payload is None and dto.normalized_payload is not None:
            effective_payload = EdgarPresenter._map_normalized_payload_dto_to_http(
                dto.normalized_payload,
            )

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
            accepted_at=dto.accepted_at,
            normalized_payload=effective_payload,
            normalized_payload_version=dto.normalized_payload_version,
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

        items: list[EdgarStatementVersionHTTP] = []
        for v in sorted_versions:
            if include_normalized and v.normalized_payload is not None:
                normalized_http = self._map_normalized_payload_dto_to_http(v.normalized_payload)
            else:
                normalized_http = None

            items.append(
                self._map_statement_dto_to_full(
                    dto=v,
                    normalized_payload=normalized_http,
                )
            )

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
    # Restatements: helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _map_restatement_metric_delta_dto(
        dto: RestatementMetricDeltaDTO,
    ) -> RestatementMetricDeltaHTTP:
        """Map a restatement metric delta DTO to the HTTP schema.

        Args:
            dto: RestatementMetricDeltaDTO instance.

        Returns:
            RestatementMetricDeltaHTTP: HTTP-facing schema.
        """
        return RestatementMetricDeltaHTTP(
            metric=dto.metric,
            old_value=dto.old_value,
            new_value=dto.new_value,
            diff=dto.diff,
        )

    @staticmethod
    def _map_restatement_summary_dto(
        dto: RestatementSummaryDTO,
    ) -> RestatementSummaryHTTP:
        """Map a restatement summary DTO to the HTTP schema.

        Args:
            dto: RestatementSummaryDTO instance.

        Returns:
            RestatementSummaryHTTP: HTTP-facing schema.
        """
        return RestatementSummaryHTTP(
            total_metrics_compared=dto.total_metrics_compared,
            total_metrics_changed=dto.total_metrics_changed,
            has_material_change=dto.has_material_change,
        )

    # ------------------------------------------------------------------
    # Restatements: delta
    # ------------------------------------------------------------------

    def present_restatement_delta(
        self,
        *,
        dto: ComputeRestatementDeltaResultDTO,
        trace_id: str | None = None,
    ) -> PresentResult[RestatementDeltaSuccessEnvelope]:
        """Present a restatement delta between two statement versions.

        The metric deltas are sorted deterministically by metric code.

        Args:
            dto:
                Application-layer restatement delta result DTO.
            trace_id:
                Optional request correlation identifier.

        Returns:
            PresentResult containing RestatementDeltaSuccessEnvelope.
        """
        # Deterministic ordering by metric code.
        sorted_deltas = sorted(dto.deltas, key=lambda d: d.metric)

        metric_http = [self._map_restatement_metric_delta_dto(delta) for delta in sorted_deltas]
        summary_http = self._map_restatement_summary_dto(dto.summary)

        payload = RestatementDeltaHTTP(
            cik=dto.cik,
            statement_type=dto.statement_type,
            fiscal_year=dto.fiscal_year,
            fiscal_period=dto.fiscal_period,
            from_version_sequence=dto.from_version_sequence,
            to_version_sequence=dto.to_version_sequence,
            summary=summary_http,
            deltas=metric_http,
        )

        _LOGGER.info(
            "edgar_presenter_restatement_delta",
            extra={
                "trace_id": trace_id,
                "cik": dto.cik,
                "statement_type": dto.statement_type.value,
                "fiscal_year": dto.fiscal_year,
                "fiscal_period": dto.fiscal_period.value,
                "from_version_sequence": dto.from_version_sequence,
                "to_version_sequence": dto.to_version_sequence,
                "total_metrics_compared": dto.summary.total_metrics_compared,
                "total_metrics_changed": dto.summary.total_metrics_changed,
                "has_material_change": dto.summary.has_material_change,
                "metrics": len(metric_http),
            },
        )

        # We keep using the BasePresenter helper for headers/status;
        # the router's response_model is the concrete RestatementDeltaSuccessEnvelope.
        envelope = RestatementDeltaSuccessEnvelope(data=payload)
        result = self.present_success(data=envelope.data, trace_id=trace_id)
        # Overwrite the body with the concrete envelope to keep OpenAPI stable.
        return PresentResult(
            body=envelope,
            status_code=result.status_code,
            headers=result.headers,
        )

    # ------------------------------------------------------------------
    # Restatements: ledger
    # ------------------------------------------------------------------

    def present_restatement_ledger(
        self,
        *,
        dto: GetRestatementLedgerResultDTO,
        trace_id: str | None = None,
    ) -> PresentResult[SuccessEnvelope[RestatementLedgerHTTP]]:
        """Present a restatement ledger across all versions of a statement.

        Ledger entries are sorted deterministically by:

            * from_version_sequence ASC
            * to_version_sequence ASC

        Args:
            dto:
                Restatement ledger result DTO.
            trace_id:
                Optional request correlation identifier.

        Returns:
            PresentResult containing SuccessEnvelope[RestatementLedgerHTTP].
        """
        # Defensive deterministic ordering.
        sorted_entries: list[RestatementLedgerEntryDTO] = sorted(
            dto.entries,
            key=lambda e: (e.from_version_sequence, e.to_version_sequence),
        )

        entries_http: list[RestatementLedgerEntryHTTP] = []
        for entry in sorted_entries:
            summary_http = self._map_restatement_summary_dto(entry.summary)
            # Metric deltas may be absent (empty list) depending on use-case wiring.
            sorted_metric_deltas = sorted(entry.deltas, key=lambda d: d.metric)
            metric_http = [
                self._map_restatement_metric_delta_dto(delta) for delta in sorted_metric_deltas
            ]

            entries_http.append(
                RestatementLedgerEntryHTTP(
                    cik=dto.cik,
                    statement_type=dto.statement_type,
                    fiscal_year=dto.fiscal_year,
                    fiscal_period=dto.fiscal_period,
                    from_version_sequence=entry.from_version_sequence,
                    to_version_sequence=entry.to_version_sequence,
                    summary=summary_http,
                    deltas=metric_http,
                ),
            )

        payload = RestatementLedgerHTTP(
            cik=dto.cik,
            statement_type=dto.statement_type,
            fiscal_year=dto.fiscal_year,
            fiscal_period=dto.fiscal_period,
            total_hops=len(entries_http),
            entries=entries_http,
        )

        _LOGGER.info(
            "edgar_presenter_restatement_ledger",
            extra={
                "trace_id": trace_id,
                "cik": dto.cik,
                "statement_type": dto.statement_type.value,
                "fiscal_year": dto.fiscal_year,
                "fiscal_period": dto.fiscal_period.value,
                "ledger_entries_count": len(entries_http),
                "min_from_version_sequence": (
                    entries_http[0].from_version_sequence if entries_http else None
                ),
                "max_to_version_sequence": (
                    entries_http[-1].to_version_sequence if entries_http else None
                ),
            },
        )

        return self.present_success(data=payload, trace_id=trace_id)

    # ------------------------------------------------------------------
    # Restatements: metric timeline
    # ------------------------------------------------------------------

    def present_restatement_timeline(
        self,
        *,
        dto: RestatementMetricTimelineDTO,
        trace_id: str | None = None,
    ) -> PresentResult[SuccessEnvelope[RestatementMetricTimelineHTTP]]:
        """Present a restatement metric timeline for a statement identity.

        The presenter enforces deterministic ordering of:

            * metric codes (alphabetical)
            * hop sequences per metric (by version_order ascending)
            * restatement_frequency and per_metric_max_delta keys

        Args:
            dto:
                Application-layer restatement metric timeline DTO.
            trace_id:
                Optional request correlation identifier.

        Returns:
            PresentResult containing SuccessEnvelope[RestatementMetricTimelineHTTP].
        """
        # Sort metrics alphabetically and hops by version_order.
        by_metric_http: dict[str, list[list[str]]] = {}
        for metric_code, hops in sorted(dto.by_metric.items(), key=lambda kv: kv[0]):
            sorted_hops = sorted(hops, key=lambda h: h[0])
            by_metric_http[metric_code] = [
                [str(version_order), delta_str] for version_order, delta_str in sorted_hops
            ]

        # Sort frequency and max-delta keys for deterministic output.
        restatement_frequency_http = {
            metric_code: dto.restatement_frequency[metric_code]
            for metric_code in sorted(dto.restatement_frequency.keys())
        }
        per_metric_max_delta_http = {
            metric_code: dto.per_metric_max_delta[metric_code]
            for metric_code in sorted(dto.per_metric_max_delta.keys())
        }

        payload = RestatementMetricTimelineHTTP(
            cik=dto.cik,
            statement_type=dto.statement_type,
            fiscal_year=dto.fiscal_year,
            fiscal_period=dto.fiscal_period,
            by_metric=by_metric_http,
            restatement_frequency=restatement_frequency_http,
            per_metric_max_delta=per_metric_max_delta_http,
            total_hops=dto.total_hops,
            timeline_severity=dto.timeline_severity.value,
        )

        _LOGGER.info(
            "edgar_presenter_restatement_timeline",
            extra={
                "trace_id": trace_id,
                "cik": dto.cik,
                "statement_type": dto.statement_type.value,
                "fiscal_year": dto.fiscal_year,
                "fiscal_period": dto.fiscal_period.value,
                "total_hops": dto.total_hops,
                "metrics": len(by_metric_http),
            },
        )

        return self.present_success(data=payload, trace_id=trace_id)

    # ------------------------------------------------------------------
    # Data-quality: mapping helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _map_normalized_fact_dto_to_http(dto: NormalizedFactDTO) -> NormalizedFactHTTP:
        """Map a NormalizedFactDTO into the HTTP schema.

        Args:
            dto: Application-layer normalized fact DTO.

        Returns:
            NormalizedFactHTTP: HTTP-facing fact schema instance.
        """
        # period_start may be null for instant facts; fall back to period_end
        # to keep the wire contract non-nullable and deterministic.
        period_start = dto.period_start or dto.period_end
        dimension = dto.dimensions or None

        return NormalizedFactHTTP(
            metric=dto.metric_code,
            label=dto.metric_label,
            unit=dto.unit,
            period_start=period_start,
            period_end=dto.period_end,
            value=dto.value,
            dimension=dimension,
            source_line_item=dto.source_line_item,
        )

    @staticmethod
    def _map_fact_quality_dto_to_http(dto: FactQualityDTO) -> FactQualityHTTP:
        """Map a FactQualityDTO into the HTTP schema."""
        return FactQualityHTTP(
            cik=dto.cik,
            statement_type=dto.statement_type.value,
            fiscal_year=dto.fiscal_year,
            fiscal_period=dto.fiscal_period.value,
            version_sequence=dto.version_sequence,
            metric=dto.metric_code,
            dimension_key=dto.dimension_key,
            severity=dto.severity.value,
            is_present=dto.is_present,
            is_non_negative=dto.is_non_negative,
            is_consistent_with_history=dto.is_consistent_with_history,
            has_known_issue=dto.has_known_issue,
            details=dto.details or {},
        )

    @staticmethod
    def _map_dq_anomaly_dto_to_http(dto: DQAnomalyDTO) -> DQAnomalyHTTP:
        """Map a DQAnomalyDTO into the HTTP schema."""
        return DQAnomalyHTTP(
            dq_run_id=dto.dq_run_id,
            metric=dto.metric_code,
            dimension_key=dto.dimension_key,
            rule_code=dto.rule_code,
            severity=dto.severity.value,
            message=dto.message,
            details=dto.details or {},
        )

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
    # Derived metrics catalog
    # ------------------------------------------------------------------

    @staticmethod
    def _map_metric_spec_to_http(
        spec: DerivedMetricSpec,
    ) -> EdgarDerivedMetricSpecHTTP:
        """Map a derived metric spec from the domain registry to HTTP schema.

        Args:
            spec: Domain-layer derived metric specification.

        Returns:
            EdgarDerivedMetricSpecHTTP: HTTP-facing spec schema.
        """
        return EdgarDerivedMetricSpecHTTP(
            code=spec.metric.value,
            category=spec.category.value,
            description=spec.description,
            is_experimental=spec.is_experimental,
            required_statement_types=sorted(
                spec.required_statement_types,
                key=lambda st: st.value,
            ),
            required_inputs=sorted(m.value for m in spec.required_inputs),
            uses_history=spec.uses_history,
            window_requirements=dict(spec.window_requirements),
        )

    def present_derived_metrics_catalog(
        self,
        *,
        specs: Iterable[DerivedMetricSpec],
        trace_id: str | None = None,
    ) -> PresentResult[SuccessEnvelope[EdgarDerivedMetricsCatalogHTTP]]:
        """Present the catalog of registered derived metrics.

        Args:
            specs:
                Iterable of derived metric specifications from the domain
                registry.
            trace_id:
                Optional request correlation identifier.

        Returns:
            PresentResult containing SuccessEnvelope[EdgarDerivedMetricsCatalogHTTP].
        """
        sorted_specs = sorted(specs, key=lambda s: s.metric.value)
        items = [self._map_metric_spec_to_http(spec) for spec in sorted_specs]

        payload = EdgarDerivedMetricsCatalogHTTP(metrics=items)

        _LOGGER.info(
            "edgar_presenter_derived_metrics_catalog",
            extra={
                "trace_id": trace_id,
                "metrics_count": len(items),
                "metric_codes": [spec.metric.value for spec in sorted_specs],
            },
        )

        return self.present_success(data=payload, trace_id=trace_id)

    # ------------------------------------------------------------------
    # Fact store: persistence result
    # ------------------------------------------------------------------

    def present_persist_normalized_facts_result(
        self,
        *,
        dto: PersistNormalizedFactsResultDTO,
        trace_id: str | None = None,
    ) -> PresentResult[SuccessEnvelope[PersistNormalizedFactsResultHTTP]]:
        """Present the result of persisting normalized facts for a statement.

        Args:
            dto: Application-layer result DTO.
            trace_id: Optional request correlation identifier.

        Returns:
            PresentResult containing SuccessEnvelope[PersistNormalizedFactsResultHTTP].
        """
        payload = PersistNormalizedFactsResultHTTP(
            cik=dto.cik,
            statement_type=dto.statement_type.value,
            fiscal_year=dto.fiscal_year,
            fiscal_period=dto.fiscal_period.value,
            version_sequence=dto.version_sequence,
            facts_persisted=dto.facts_persisted,
        )

        _LOGGER.info(
            "edgar_presenter_persist_normalized_facts_result",
            extra={
                "trace_id": trace_id,
                "cik": dto.cik,
                "statement_type": dto.statement_type.value,
                "fiscal_year": dto.fiscal_year,
                "fiscal_period": dto.fiscal_period.value,
                "version_sequence": dto.version_sequence,
                "facts_persisted": dto.facts_persisted,
            },
        )

        return self.present_success(data=payload, trace_id=trace_id)

    # ------------------------------------------------------------------
    # Data-quality: run result
    # ------------------------------------------------------------------

    def present_run_statement_dq_result(
        self,
        *,
        dto: RunStatementDQResultDTO,
        trace_id: str | None = None,
    ) -> PresentResult[SuccessEnvelope[RunStatementDQResultHTTP]]:
        """Present the result summary of a statement-level DQ run.

        Args:
            dto: Application-layer RunStatementDQResultDTO.
            trace_id: Optional request correlation identifier.

        Returns:
            PresentResult containing SuccessEnvelope[RunStatementDQResultHTTP].
        """
        payload = RunStatementDQResultHTTP(
            dq_run_id=dto.dq_run_id,
            cik=dto.cik,
            statement_type=dto.statement_type.value,
            fiscal_year=dto.fiscal_year,
            fiscal_period=dto.fiscal_period.value,
            version_sequence=dto.version_sequence,
            rule_set_version=dto.rule_set_version,
            scope_type=dto.scope_type,
            history_lookback=dto.history_lookback,
            executed_at=dto.executed_at,
            facts_evaluated=dto.facts_evaluated,
            anomaly_count=dto.anomaly_count,
            max_severity=dto.max_severity.value if dto.max_severity is not None else None,
        )

        _LOGGER.info(
            "edgar_presenter_run_statement_dq_result",
            extra={
                "trace_id": trace_id,
                "dq_run_id": dto.dq_run_id,
                "cik": dto.cik,
                "statement_type": dto.statement_type.value,
                "fiscal_year": dto.fiscal_year,
                "fiscal_period": dto.fiscal_period.value,
                "version_sequence": dto.version_sequence,
                "rule_set_version": dto.rule_set_version,
                "scope_type": dto.scope_type,
                "history_lookback": dto.history_lookback,
                "facts_evaluated": dto.facts_evaluated,
                "anomaly_count": dto.anomaly_count,
                "max_severity": dto.max_severity.value if dto.max_severity else None,
            },
        )

        return self.present_success(data=payload, trace_id=trace_id)

    # ------------------------------------------------------------------
    # Data-quality: statement-level overlay
    # ------------------------------------------------------------------

    def present_statement_dq_overlay(
        self,
        *,
        dto: StatementDQOverlayDTO,
        trace_id: str | None = None,
    ) -> PresentResult[SuccessEnvelope[StatementDQOverlayHTTP]]:
        """Present a statement-level fact + DQ overlay.

        Args:
            dto:
                Application-layer StatementDQOverlayDTO.
            trace_id:
                Optional request correlation identifier.

        Returns:
            PresentResult containing SuccessEnvelope[StatementDQOverlayHTTP].
        """
        # Defensive deterministic ordering:
        #  - facts by (metric_code, period_end, dimension_key)
        #  - fact_quality by (metric_code, dimension_key)
        #  - anomalies by (severity desc, rule_code, metric, dimension_key)
        facts_sorted = sorted(
            dto.facts,
            key=lambda f: (f.metric_code, f.period_end, f.dimension_key),
        )
        fact_quality_sorted = sorted(
            dto.fact_quality,
            key=lambda fq: (fq.metric_code, fq.dimension_key),
        )
        anomalies_sorted = sorted(
            dto.anomalies,
            key=lambda a: (
                a.severity.value,
                a.rule_code,
                a.metric_code or "",
                a.dimension_key or "",
            ),
            reverse=True,
        )

        facts_http = [self._map_normalized_fact_dto_to_http(f) for f in facts_sorted]
        fact_quality_http = [self._map_fact_quality_dto_to_http(fq) for fq in fact_quality_sorted]
        anomalies_http = [self._map_dq_anomaly_dto_to_http(a) for a in anomalies_sorted]

        payload = StatementDQOverlayHTTP(
            cik=dto.cik,
            statement_type=dto.statement_type.value,
            fiscal_year=dto.fiscal_year,
            fiscal_period=dto.fiscal_period.value,
            version_sequence=dto.version_sequence,
            accounting_standard=dto.accounting_standard.value,
            statement_date=dto.statement_date,
            currency=dto.currency,
            dq_run_id=dto.dq_run_id,
            dq_rule_set_version=dto.dq_rule_set_version,
            dq_executed_at=dto.dq_executed_at,
            max_severity=dto.max_severity.value if dto.max_severity is not None else None,
            facts=facts_http,
            fact_quality=fact_quality_http,
            anomalies=anomalies_http,
        )

        _LOGGER.info(
            "edgar_presenter_statement_dq_overlay",
            extra={
                "trace_id": trace_id,
                "cik": dto.cik,
                "statement_type": dto.statement_type.value,
                "fiscal_year": dto.fiscal_year,
                "fiscal_period": dto.fiscal_period.value,
                "version_sequence": dto.version_sequence,
                "dq_run_id": dto.dq_run_id,
                "dq_rule_set_version": dto.dq_rule_set_version,
                "facts": len(facts_http),
                "fact_quality_records": len(fact_quality_http),
                "anomalies": len(anomalies_http),
                "max_severity": dto.max_severity.value if dto.max_severity else None,
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
