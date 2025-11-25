# Copyright (c) Stacklion.
# SPDX-License-Identifier: MIT
"""Presenter: EDGAR filings and statements → HTTP envelopes.

Purpose:
    Map EDGAR application-layer DTOs into canonical HTTP schemas and envelopes:

        * PaginatedEnvelope[EdgarFilingHTTP]
        * PaginatedEnvelope[EdgarStatementVersionSummaryHTTP]
        * SuccessEnvelope[EdgarFilingHTTP]
        * SuccessEnvelope[EdgarStatementVersionListHTTP]

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
from typing import Any

from stacklion_api.adapters.presenters.base_presenter import (
    BasePresenter,
    PresentResult,
)
from stacklion_api.adapters.schemas.http.edgar_schemas import (
    EdgarFilingHTTP,
    EdgarStatementVersionHTTP,
    EdgarStatementVersionListHTTP,
    EdgarStatementVersionSummaryHTTP,
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
