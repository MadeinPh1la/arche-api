# src/stacklion_api/adapters/routers/edgar_router.py
# Copyright (c)
# SPDX-License-Identifier: MIT
"""EDGAR Router (v1).

Synopsis:
    HTTP surface for EDGAR filings and normalized statement versions.

Endpoints (all under /v1/edgar):
    - GET /v1/edgar/companies/{cik}/filings
        → PaginatedEnvelope of filing headers.
    - GET /v1/edgar/companies/{cik}/filings/{accession_id}
        → SuccessEnvelope with filing detail.
    - GET /v1/edgar/companies/{cik}/statements
        → PaginatedEnvelope of statement versions.
    - GET /v1/edgar/companies/{cik}/filings/{accession_id}/statements
        → SuccessEnvelope with statement versions for a filing.
    - GET /v1/edgar/derived-metrics/catalog
        → SuccessEnvelope with derived metrics catalog.
    - GET /v1/edgar/derived-metrics/time-series
        → SuccessEnvelope with derived metrics time-series points.
    - GET /v1/edgar/statements/restatements/delta
        → SuccessEnvelope with restatement delta between two versions.
    - GET /v1/edgar/statements/restatements/ledger
        → SuccessEnvelope with restatement ledger over version history.
    - GET /v1/edgar/companies/{cik}/statements/overrides/trace
        → SuccessEnvelope with override observability trace for a statement.


Design:
    * Router handles HTTP validation and error mapping to envelopes.
    * Controllers orchestrate use cases only (no direct repo/infra).
    * Presenters shape DTOs into canonical envelopes and HTTP schemas.
"""


from __future__ import annotations

from datetime import date
from typing import Annotated, Any, cast

from fastapi import Depends, HTTPException, Path, Query, Request, Response, status
from fastapi.responses import JSONResponse

from stacklion_api.adapters.controllers.edgar_controller import EdgarController
from stacklion_api.adapters.dependencies.edgar_uow import get_edgar_uow
from stacklion_api.adapters.presenters.base_presenter import PresentResult
from stacklion_api.adapters.presenters.edgar_dq_presenter import (
    present_run_statement_dq,
    present_statement_dq_overlay,
)
from stacklion_api.adapters.presenters.edgar_overrides_presenter import (
    present_statement_override_trace,
)
from stacklion_api.adapters.presenters.edgar_presenter import EdgarPresenter
from stacklion_api.adapters.routers.base_router import BaseRouter, PageParams
from stacklion_api.adapters.schemas.http.edgar_dq_schemas import (
    RunStatementDQResultHTTP,
    StatementDQOverlayHTTP,
)
from stacklion_api.adapters.schemas.http.edgar_overrides_schemas import (
    StatementOverrideTraceHTTP,
)
from stacklion_api.adapters.schemas.http.edgar_schemas import (
    EdgarDerivedMetricsCatalogHTTP,
    EdgarDerivedMetricsTimeSeriesHTTP,
    EdgarFilingHTTP,
    EdgarStatementVersionListHTTP,
    RestatementLedgerHTTP,
    RestatementMetricTimelineHTTP,
)
from stacklion_api.adapters.schemas.http.envelopes import (
    ErrorEnvelope,
    ErrorObject,
    PaginatedEnvelope,
    RestatementDeltaSuccessEnvelope,
    SuccessEnvelope,
)
from stacklion_api.application.schemas.dto.edgar import EdgarFilingDTO
from stacklion_api.application.uow import UnitOfWork
from stacklion_api.application.use_cases.statements.get_statement_override_trace import (
    GetStatementOverrideTraceRequest,
    GetStatementOverrideTraceUseCase,
)
from stacklion_api.application.use_cases.statements.get_statement_with_dq_overlay import (
    GetStatementWithDQOverlayRequest,
    GetStatementWithDQOverlayUseCase,
)
from stacklion_api.application.use_cases.statements.run_statement_dq import (
    RunStatementDQRequest,
    RunStatementDQUseCase,
)
from stacklion_api.dependencies.edgar import get_edgar_controller
from stacklion_api.domain.enums.derived_metric import DerivedMetric
from stacklion_api.domain.enums.edgar import FilingType, FiscalPeriod, StatementType
from stacklion_api.domain.exceptions.edgar import (
    EdgarIngestionError,
    EdgarMappingError,
    EdgarNotFound,
)
from stacklion_api.domain.services.derived_metrics_engine import DERIVED_METRIC_SPECS
from stacklion_api.infrastructure.logging.logger import get_json_logger

logger = get_json_logger(__name__)

# v1 EDGAR router
router = BaseRouter(version="v1", resource="edgar", tags=["EDGAR Filings"])
presenter = EdgarPresenter()


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _normalize_cik(raw: str) -> str:
    """Normalize and validate a CIK string."""
    cik = raw.strip()
    if not cik:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="CIK must not be empty",
        )
    if not cik.isdigit():
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="CIK must contain only digits",
        )
    return cik


def _error_envelope(
    *,
    http_status: int,
    code: str,
    message: str,
    trace_id: str | None,
    details: dict[str, Any] | None = None,
) -> ErrorEnvelope:
    """Construct an ErrorEnvelope with canonical fields."""
    return ErrorEnvelope(
        error=ErrorObject(
            code=code,
            http_status=http_status,
            message=message,
            details=details or {},
            trace_id=trace_id,
        )
    )


def _apply_present_result(response: Response, result: PresentResult[Any]) -> Any:
    """Apply presenter-controlled headers/status and return the body."""
    presenter.apply_headers(result, response)
    body = result.body
    if body is None:
        return {}
    return body


# ---------------------------------------------------------------------------
# Routes: Filings
# ---------------------------------------------------------------------------


@router.get(
    "/companies/{cik}/filings",
    response_model=PaginatedEnvelope,
    status_code=status.HTTP_200_OK,
    responses=cast("dict[int | str, dict[str, Any]]", BaseRouter.std_error_responses()),
    summary="List EDGAR filings for a company",
    description=(
        "Returns a paginated list of normalized EDGAR filing headers for the given CIK. "
        "Supports optional filtering by filing type and filing date window.\n\n"
        "Deterministic ordering: latest filings first (filing_date desc, accession_id desc)."
    ),
)
async def list_filings(
    request: Request,
    response: Response,
    controller: Annotated[EdgarController, Depends(get_edgar_controller)],
    page_params: Annotated[PageParams, Depends(BaseRouter.page_params)],
    cik: Annotated[
        str,
        Path(
            description="Company CIK as digits (no leading 'CIK' prefix).",
            examples=["0000320193"],
        ),
    ],
    filing_types: Annotated[
        list[FilingType] | None,
        Query(
            description=(
                "Optional list of filing types to include (e.g., 10-K,10-Q). "
                "If omitted, all supported filing types are considered."
            ),
            examples=[["10-K", "10-Q"]],
        ),
    ] = None,
    from_date: Annotated[
        date | None,
        Query(
            description="Optional lower bound on filing_date (inclusive, YYYY-MM-DD).",
            examples=["2023-01-01"],
        ),
    ] = None,
    to_date: Annotated[
        date | None,
        Query(
            description="Optional upper bound on filing_date (inclusive, YYYY-MM-DD).",
            examples=["2024-12-31"],
        ),
    ] = None,
    include_amendments: Annotated[
        bool,
        Query(
            description="Whether to include amended forms (e.g., 10-K/A).",
        ),
    ] = True,
) -> PaginatedEnvelope[Any] | JSONResponse:
    """List EDGAR filings for a company."""
    del request  # reserved for future auth/feature flags
    trace_id = response.headers.get("X-Request-ID")
    normalized_cik = _normalize_cik(cik)

    logger.info(
        "edgar.api.list_filings.start",
        extra={
            "cik": normalized_cik,
            "from_date": from_date.isoformat() if from_date else None,
            "to_date": to_date.isoformat() if to_date else None,
            "filing_types": [ft.value for ft in (filing_types or [])],
            "include_amendments": include_amendments,
            "page": page_params.page,
            "page_size": page_params.page_size,
            "trace_id": trace_id,
        },
    )

    try:
        dto_list, total = await controller.list_filings(
            cik=normalized_cik,
            filing_types=filing_types,
            from_date=from_date,
            to_date=to_date,
            include_amendments=include_amendments,
            page=page_params.page,
            page_size=page_params.page_size,
        )

        result = presenter.present_filings_page(
            dtos=dto_list,
            page=page_params.page,
            page_size=page_params.page_size,
            total=total,
            trace_id=trace_id,
        )
        body = _apply_present_result(response, result)

        logger.info(
            "edgar.api.list_filings.success",
            extra={
                "cik": normalized_cik,
                "count": len(dto_list),
                "total": total,
                "page": page_params.page,
                "page_size": page_params.page_size,
                "trace_id": trace_id,
            },
        )

        return cast(PaginatedEnvelope[Any], body)

    except EdgarNotFound as exc:
        envelope = _error_envelope(
            http_status=404,
            code="EDGAR_FILING_NOT_FOUND",
            message=str(exc),
            trace_id=trace_id,
        )
        return JSONResponse(status_code=404, content=envelope.model_dump(mode="json"))

    except EdgarMappingError as exc:
        envelope = _error_envelope(
            http_status=500,
            code="EDGAR_MAPPING_ERROR",
            message=str(exc),
            trace_id=trace_id,
            details=getattr(exc, "details", None),
        )
        return JSONResponse(status_code=500, content=envelope.model_dump(mode="json"))

    except EdgarIngestionError as exc:
        envelope = _error_envelope(
            http_status=502,
            code="EDGAR_UPSTREAM_ERROR",
            message=str(exc),
            trace_id=trace_id,
            details=getattr(exc, "details", None),
        )
        return JSONResponse(status_code=502, content=envelope.model_dump(mode="json"))

    except Exception as exc:  # pragma: no cover - defensive
        logger.exception(
            "edgar.api.list_filings.unhandled",
            extra={"cik": normalized_cik, "trace_id": trace_id},
        )
        envelope = _error_envelope(
            http_status=503,
            code="EDGAR_UNAVAILABLE",
            message="EDGAR service is temporarily unavailable.",
            trace_id=trace_id,
            details={"reason": type(exc).__name__},
        )
        return JSONResponse(status_code=503, content=envelope.model_dump(mode="json"))


@router.get(
    "/companies/{cik}/filings/{accession_id}",
    response_model=SuccessEnvelope[EdgarFilingHTTP] | ErrorEnvelope,
    status_code=status.HTTP_200_OK,
    responses=cast("dict[int | str, dict[str, Any]]", BaseRouter.std_error_responses()),
    summary="Get EDGAR filing detail",
    description=(
        "Return normalized EDGAR filing metadata for a specific filing. "
        "Future versions may include normalized statement and long-form payloads."
    ),
)
async def get_filing(
    request: Request,
    response: Response,
    controller: Annotated[EdgarController, Depends(get_edgar_controller)],
    cik: Annotated[
        str,
        Path(
            description="Company CIK as digits.",
            examples=["0000320193"],
        ),
    ],
    accession_id: Annotated[
        str,
        Path(
            description="EDGAR accession ID (e.g., 0000320193-24-000012).",
            examples=["0000320193-24-000012"],
        ),
    ],
    include_statements: Annotated[
        bool,
        Query(
            description="Reserved for future use; currently ignored.",
        ),
    ] = True,
    include_long_form: Annotated[
        bool,
        Query(
            description="Reserved for future normalized long-form payload; currently ignored.",
        ),
    ] = False,
) -> SuccessEnvelope[EdgarFilingHTTP] | ErrorEnvelope:
    """Get EDGAR filing detail for a specific accession."""
    del request, include_statements, include_long_form
    trace_id = response.headers.get("X-Request-ID")
    normalized_cik = _normalize_cik(cik)
    acc = accession_id.strip()

    if not acc:
        response.status_code = status.HTTP_400_BAD_REQUEST
        return _error_envelope(
            http_status=400,
            code="VALIDATION_ERROR",
            message="accession_id must not be empty.",
            trace_id=trace_id,
        )

    logger.info(
        "edgar.api.get_filing.start",
        extra={
            "cik": normalized_cik,
            "accession_id": acc,
            "trace_id": trace_id,
        },
    )

    try:
        dto: EdgarFilingDTO = await controller.get_filing(
            cik=normalized_cik,
            accession_id=acc,
        )
        result = presenter.present_filing_detail(dto=dto, trace_id=trace_id)
        body = _apply_present_result(response, result)

        logger.info(
            "edgar.api.get_filing.success",
            extra={
                "cik": normalized_cik,
                "accession_id": acc,
                "trace_id": trace_id,
            },
        )
        return cast(SuccessEnvelope[EdgarFilingHTTP], body)

    except EdgarNotFound as exc:
        response.status_code = status.HTTP_404_NOT_FOUND
        return _error_envelope(
            http_status=404,
            code="EDGAR_FILING_NOT_FOUND",
            message=str(exc),
            trace_id=trace_id,
        )

    except EdgarMappingError as exc:
        response.status_code = status.HTTP_500_INTERNAL_SERVER_ERROR
        return _error_envelope(
            http_status=500,
            code="EDGAR_MAPPING_ERROR",
            message=str(exc),
            trace_id=trace_id,
            details=getattr(exc, "details", None),
        )

    except EdgarIngestionError as exc:
        # Tests simulate some not-found cases via EdgarIngestionError("Not found")
        msg = str(exc)
        if msg.lower().startswith("not found"):
            response.status_code = status.HTTP_404_NOT_FOUND
            return _error_envelope(
                http_status=404,
                code="EDGAR_FILING_NOT_FOUND",
                message=msg,
                trace_id=trace_id,
                details=getattr(exc, "details", None),
            )

        response.status_code = status.HTTP_502_BAD_GATEWAY
        return _error_envelope(
            http_status=502,
            code="EDGAR_UPSTREAM_ERROR",
            message=msg,
            trace_id=trace_id,
            details=getattr(exc, "details", None),
        )

    except Exception as exc:  # pragma: no cover
        logger.exception(
            "edgar.api.get_filing.unhandled",
            extra={"cik": normalized_cik, "accession_id": acc, "trace_id": trace_id},
        )
        response.status_code = status.HTTP_503_SERVICE_UNAVAILABLE
        return _error_envelope(
            http_status=503,
            code="EDGAR_UNAVAILABLE",
            message="EDGAR service is temporarily unavailable.",
            trace_id=trace_id,
            details={"reason": type(exc).__name__},
        )


# ---------------------------------------------------------------------------
# Routes: Statement versions
# ---------------------------------------------------------------------------


@router.get(
    "/companies/{cik}/statements",
    response_model=PaginatedEnvelope,
    status_code=status.HTTP_200_OK,
    responses=cast("dict[int | str, dict[str, Any]]", BaseRouter.std_error_responses()),
    summary="List EDGAR statement versions for a company",
    description=(
        "Returns a paginated list of normalized statement versions (income, "
        "balance sheet, cash flow) for a company over a date range.\n\n"
        "Deterministic ordering: statement_date desc, version_sequence desc."
    ),
)
async def list_statement_versions(
    request: Request,
    response: Response,
    controller: Annotated[EdgarController, Depends(get_edgar_controller)],
    page_params: Annotated[PageParams, Depends(BaseRouter.page_params)],
    cik: Annotated[
        str,
        Path(
            description="Company CIK as digits.",
            examples=["0000320193"],
        ),
    ],
    statement_type: Annotated[
        str,
        Query(
            description=(
                "Statement type filter " "(INCOME_STATEMENT, BALANCE_SHEET, CASH_FLOW_STATEMENT)."
            ),
        ),
    ],
    from_date: Annotated[
        date | None,
        Query(
            description="Optional lower bound on statement_date (inclusive, YYYY-MM-DD).",
        ),
    ] = None,
    to_date: Annotated[
        date | None,
        Query(
            description="Optional upper bound on statement_date (inclusive, YYYY-MM-DD).",
        ),
    ] = None,
    include_restated: Annotated[
        bool,
        Query(
            description="Whether to include restated versions (default: false).",
        ),
    ] = False,
) -> PaginatedEnvelope[Any] | JSONResponse:
    """List statement versions for a company."""
    del request
    trace_id = response.headers.get("X-Request-ID")
    normalized_cik = _normalize_cik(cik)

    # Manual parse so invalid statement_type returns 400 envelope, not FastAPI 422.
    try:
        typed_statement_type = StatementType(statement_type)
    except ValueError:
        envelope = _error_envelope(
            http_status=400,
            code="VALIDATION_ERROR",
            message="Invalid statement_type.",
            trace_id=trace_id,
            details={"statement_type": statement_type},
        )
        return JSONResponse(status_code=400, content=envelope.model_dump(mode="json"))

    logger.info(
        "edgar.api.list_statement_versions.start",
        extra={
            "cik": normalized_cik,
            "statement_type": typed_statement_type.value,
            "from_date": from_date.isoformat() if from_date else None,
            "to_date": to_date.isoformat() if to_date else None,
            "include_restated": include_restated,
            "page": page_params.page,
            "page_size": page_params.page_size,
            "trace_id": trace_id,
        },
    )

    try:
        dto_list, total = await controller.list_statements(
            cik=normalized_cik,
            statement_type=typed_statement_type,
            from_date=from_date,
            to_date=to_date,
            include_restated=include_restated,
            page=page_params.page,
            page_size=page_params.page_size,
        )

        result = presenter.present_statement_versions_page(
            dtos=dto_list,
            page=page_params.page,
            page_size=page_params.page_size,
            total=total,
            trace_id=trace_id,
        )
        body = _apply_present_result(response, result)

        logger.info(
            "edgar.api.list_statement_versions.success",
            extra={
                "cik": normalized_cik,
                "statement_type": typed_statement_type.value,
                "count": len(dto_list),
                "total": total,
                "page": page_params.page,
                "page_size": page_params.page_size,
                "trace_id": trace_id,
            },
        )

        return cast(PaginatedEnvelope[Any], body)

    except EdgarNotFound as exc:
        envelope = _error_envelope(
            http_status=404,
            code="EDGAR_STATEMENTS_NOT_FOUND",
            message=str(exc),
            trace_id=trace_id,
        )
        return JSONResponse(status_code=404, content=envelope.model_dump(mode="json"))

    except EdgarMappingError as exc:
        envelope = _error_envelope(
            http_status=500,
            code="EDGAR_MAPPING_ERROR",
            message=str(exc),
            trace_id=trace_id,
            details=getattr(exc, "details", None),
        )
        return JSONResponse(status_code=500, content=envelope.model_dump(mode="json"))

    except EdgarIngestionError as exc:
        envelope = _error_envelope(
            http_status=502,
            code="EDGAR_UPSTREAM_ERROR",
            message=str(exc),
            trace_id=trace_id,
            details=getattr(exc, "details", None),
        )
        return JSONResponse(status_code=502, content=envelope.model_dump(mode="json"))

    except Exception as exc:  # pragma: no cover
        logger.exception(
            "edgar.api.list_statement_versions.unhandled",
            extra={"cik": normalized_cik, "trace_id": trace_id},
        )
        envelope = _error_envelope(
            http_status=503,
            code="EDGAR_UNAVAILABLE",
            message="EDGAR service is temporarily unavailable.",
            trace_id=trace_id,
            details={"reason": type(exc).__name__},
        )
        return JSONResponse(status_code=503, content=envelope.model_dump(mode="json"))


@router.get(
    "/companies/{cik}/filings/{accession_id}/statements",
    response_model=SuccessEnvelope[EdgarStatementVersionListHTTP] | ErrorEnvelope,
    status_code=status.HTTP_200_OK,
    responses=cast("dict[int | str, dict[str, Any]]", BaseRouter.std_error_responses()),
    summary="Get statement versions for a filing",
    description=(
        "Return statement versions (income, balance sheet, cash flow) associated with "
        "a specific EDGAR filing."
    ),
)
async def get_statement_versions_for_filing(
    request: Request,
    response: Response,
    controller: Annotated[EdgarController, Depends(get_edgar_controller)],
    cik: Annotated[
        str,
        Path(
            description="Company CIK as digits.",
            examples=["0000320193"],
        ),
    ],
    accession_id: Annotated[
        str,
        Path(
            description="EDGAR accession ID (e.g., 0000320193-24-000012).",
            examples=["0000320193-24-000012"],
        ),
    ],
    statement_type: Annotated[
        StatementType | None,
        Query(
            description=(
                "Optional statement type filter "
                "(INCOME_STATEMENT, BALANCE_SHEET, CASH_FLOW_STATEMENT)."
            ),
        ),
    ] = None,
    include_restated: Annotated[
        bool,
        Query(
            description="Whether to include restated versions (default: false).",
        ),
    ] = False,
    include_normalized: Annotated[
        bool,
        Query(
            description=(
                "Whether to include long-form normalized payloads derived from "
                "statement versions. When false, normalized_payload is always null."
            ),
        ),
    ] = False,
) -> SuccessEnvelope[EdgarStatementVersionListHTTP] | ErrorEnvelope:
    """Retrieve statement versions associated with a specific filing."""
    del request
    trace_id = response.headers.get("X-Request-ID")
    normalized_cik = _normalize_cik(cik)
    acc = accession_id.strip()

    if not acc:
        response.status_code = status.HTTP_400_BAD_REQUEST
        return _error_envelope(
            http_status=400,
            code="VALIDATION_ERROR",
            message="accession_id must not be empty.",
            trace_id=trace_id,
        )

    logger.info(
        "edgar.api.get_statement_versions_for_filing.start",
        extra={
            "cik": normalized_cik,
            "accession_id": acc,
            "statement_type": statement_type.value if statement_type else None,
            "include_restated": include_restated,
            "include_normalized": include_normalized,
            "trace_id": trace_id,
        },
    )

    try:
        filing_dto, versions = await controller.get_statement_versions_for_filing(
            cik=normalized_cik,
            accession_id=acc,
            statement_type=statement_type,
            include_restated=include_restated,
            include_normalized=include_normalized,
        )

        result = presenter.present_statement_versions_for_filing(
            filing=filing_dto,
            versions=versions,
            include_normalized=include_normalized,
            trace_id=trace_id,
        )
        body = _apply_present_result(response, result)

        logger.info(
            "edgar.api.get_statement_versions_for_filing.success",
            extra={
                "cik": normalized_cik,
                "accession_id": acc,
                "count": len(versions),
                "include_normalized": include_normalized,
                "trace_id": trace_id,
            },
        )
        return cast(SuccessEnvelope[EdgarStatementVersionListHTTP], body)

    except EdgarNotFound as exc:
        response.status_code = status.HTTP_404_NOT_FOUND
        return _error_envelope(
            http_status=404,
            code="EDGAR_STATEMENTS_NOT_FOUND",
            message=str(exc),
            trace_id=trace_id,
        )

    except EdgarMappingError as exc:
        response.status_code = status.HTTP_500_INTERNAL_SERVER_ERROR
        return _error_envelope(
            http_status=500,
            code="EDGAR_MAPPING_ERROR",
            message=str(exc),
            trace_id=trace_id,
            details=getattr(exc, "details", None),
        )

    except EdgarIngestionError as exc:
        response.status_code = status.HTTP_502_BAD_GATEWAY
        return _error_envelope(
            http_status=502,
            code="EDGAR_UPSTREAM_ERROR",
            message=str(exc),
            trace_id=trace_id,
            details=getattr(exc, "details", None),
        )

    except Exception as exc:  # pragma: no cover
        logger.exception(
            "edgar.api.get_statement_versions_for_filing.unhandled",
            extra={"cik": normalized_cik, "accession_id": acc, "trace_id": trace_id},
        )
        response.status_code = status.HTTP_503_SERVICE_UNAVAILABLE
        return _error_envelope(
            http_status=503,
            code="EDGAR_UNAVAILABLE",
            message="EDGAR service is temporarily unavailable.",
            trace_id=trace_id,
            details={"reason": type(exc).__name__},
        )


# ---------------------------------------------------------------------------
# Routes: Derived metrics catalog
# ---------------------------------------------------------------------------


@router.get(
    "/derived-metrics/catalog",
    response_model=SuccessEnvelope[EdgarDerivedMetricsCatalogHTTP] | ErrorEnvelope,
    status_code=status.HTTP_200_OK,
    responses=cast("dict[int | str, dict[str, Any]]", BaseRouter.std_error_responses()),
    summary="List derived metrics catalog",
    description=(
        "Expose the catalog of all registered derived metrics from the EDGAR "
        "derived-metrics engine. This endpoint provides introspection into "
        "each metric's category, inputs, and history requirements."
    ),
)
async def get_derived_metrics_catalog(
    request: Request,
    response: Response,
) -> SuccessEnvelope[EdgarDerivedMetricsCatalogHTTP] | ErrorEnvelope | JSONResponse:
    """Return the catalog of registered derived metrics."""
    del request
    trace_id = response.headers.get("X-Request-ID")

    logger.info(
        "edgar.api.get_derived_metrics_catalog.start",
        extra={"trace_id": trace_id},
    )

    try:
        specs = list(DERIVED_METRIC_SPECS.values())
        # Deterministic ordering by metric code.
        sorted_specs = sorted(specs, key=lambda s: s.metric.value)

        result = presenter.present_derived_metrics_catalog(
            specs=sorted_specs,
            trace_id=trace_id,
        )
        body = _apply_present_result(response, result)

        logger.info(
            "edgar.api.get_derived_metrics_catalog.success",
            extra={
                "trace_id": trace_id,
                "metrics_count": len(sorted_specs),
            },
        )

        return cast(SuccessEnvelope[EdgarDerivedMetricsCatalogHTTP], body)

    except Exception as exc:  # pragma: no cover - defensive
        logger.exception(
            "edgar.api.get_derived_metrics_catalog.unhandled",
            extra={"trace_id": trace_id},
        )
        envelope = _error_envelope(
            http_status=503,
            code="EDGAR_UNAVAILABLE",
            message="EDGAR service is temporarily unavailable.",
            trace_id=trace_id,
            details={"reason": type(exc).__name__},
        )
        return JSONResponse(status_code=503, content=envelope.model_dump(mode="json"))


# ---------------------------------------------------------------------------
# Routes: Derived metrics time series
# ---------------------------------------------------------------------------


@router.get(
    "/derived-metrics/time-series",
    response_model=SuccessEnvelope[EdgarDerivedMetricsTimeSeriesHTTP] | ErrorEnvelope,
    status_code=status.HTTP_200_OK,
    responses=cast("dict[int | str, dict[str, Any]]", BaseRouter.std_error_responses()),
    summary="Get derived metrics time series",
    description=(
        "Return a derived metrics time series for one or more companies, "
        "built on top of normalized EDGAR statement payloads.\n\n"
        "This endpoint exposes a panel-friendly structure suitable for "
        "modeling workflows. Metrics are requested by code (e.g., "
        "GROSS_MARGIN, ROE) and are computed per (cik, statement_date, "
        "fiscal_period) using the derived-metrics engine."
    ),
)
async def get_derived_metrics_timeseries(
    request: Request,
    response: Response,
    controller: Annotated[EdgarController, Depends(get_edgar_controller)],
    ciks: Annotated[
        list[str],
        Query(
            description="One or more company CIKs as digits (no 'CIK' prefix).",
            examples=[["0000320193", "0000789019"]],
        ),
    ],
    statement_type: Annotated[
        str,
        Query(
            description=(
                "Statement type used as the base for derived metrics "
                "(INCOME_STATEMENT, BALANCE_SHEET, CASH_FLOW_STATEMENT)."
            ),
        ),
    ],
    metrics: Annotated[
        list[DerivedMetric] | None,
        Query(
            description=(
                "Optional list of derived metric codes to include "
                "(e.g., GROSS_MARGIN, ROE). If omitted, all registered "
                "derived metrics are considered."
            ),
            examples=[["GROSS_MARGIN", "REVENUE_GROWTH_YOY", "ROE"]],
        ),
    ] = None,
    frequency: Annotated[
        str,
        Query(
            description="Time-series frequency: 'annual' or 'quarterly' (default: 'annual').",
        ),
    ] = "annual",
    from_date: Annotated[
        date | None,
        Query(
            description="Optional lower bound on statement_date (inclusive, YYYY-MM-DD).",
        ),
    ] = None,
    to_date: Annotated[
        date | None,
        Query(
            description="Optional upper bound on statement_date (inclusive, YYYY-MM-DD).",
        ),
    ] = None,
) -> SuccessEnvelope[EdgarDerivedMetricsTimeSeriesHTTP] | ErrorEnvelope | JSONResponse:
    """Get a derived metrics time series."""
    del request
    trace_id = response.headers.get("X-Request-ID")

    # Normalize and validate CIKs.
    normalized_ciks: list[str] = []
    for raw in ciks:
        try:
            normalized_ciks.append(_normalize_cik(raw))
        except HTTPException as exc:
            response.status_code = exc.status_code
            return _error_envelope(
                http_status=exc.status_code,
                code="VALIDATION_ERROR",
                message=str(exc.detail),
                trace_id=trace_id,
                details={"cik": raw},
            )

    if not normalized_ciks:
        response.status_code = status.HTTP_400_BAD_REQUEST
        return _error_envelope(
            http_status=400,
            code="VALIDATION_ERROR",
            message="At least one non-empty CIK must be provided.",
            trace_id=trace_id,
        )

    # Manual parse of statement_type to keep FastAPI from returning 422.
    try:
        typed_statement_type = StatementType(statement_type)
    except ValueError:
        envelope = _error_envelope(
            http_status=400,
            code="VALIDATION_ERROR",
            message="Invalid statement_type.",
            trace_id=trace_id,
            details={"statement_type": statement_type},
        )
        return JSONResponse(status_code=400, content=envelope.model_dump(mode="json"))

    normalized_frequency = frequency.lower()
    if normalized_frequency not in {"annual", "quarterly"}:
        response.status_code = status.HTTP_400_BAD_REQUEST
        return _error_envelope(
            http_status=400,
            code="VALIDATION_ERROR",
            message="frequency must be 'annual' or 'quarterly'.",
            trace_id=trace_id,
            details={"frequency": frequency},
        )

    logger.info(
        "edgar.api.get_derived_metrics_timeseries.start",
        extra={
            "ciks": normalized_ciks,
            "statement_type": typed_statement_type.value,
            "metrics": [m.value for m in (metrics or [])],
            "frequency": normalized_frequency,
            "from_date": from_date.isoformat() if from_date else None,
            "to_date": to_date.isoformat() if to_date else None,
            "trace_id": trace_id,
        },
    )

    # Compute effective window for the HTTP payload to align with the use case.
    effective_from_date = from_date or date(1994, 1, 1)
    effective_to_date = to_date or date.today()

    try:
        dtos = await controller.get_derived_metrics_timeseries(
            ciks=normalized_ciks,
            statement_type=typed_statement_type,
            metrics=metrics,
            frequency=normalized_frequency,
            from_date=from_date,
            to_date=to_date,
        )

        result = presenter.present_derived_timeseries(
            dtos=dtos,
            ciks=normalized_ciks,
            statement_type=typed_statement_type,
            frequency=normalized_frequency,
            from_date=effective_from_date,
            to_date=effective_to_date,
            trace_id=trace_id,
        )
        body = _apply_present_result(response, result)

        logger.info(
            "edgar.api.get_derived_metrics_timeseries.success",
            extra={
                "ciks": normalized_ciks,
                "statement_type": typed_statement_type.value,
                "frequency": normalized_frequency,
                "from_date": effective_from_date.isoformat(),
                "to_date": effective_to_date.isoformat(),
                "points": len(dtos),
                "trace_id": trace_id,
            },
        )

        return cast(SuccessEnvelope[EdgarDerivedMetricsTimeSeriesHTTP], body)

    except EdgarNotFound as exc:
        # If the use case chooses to signal empty/unavailable via NotFound.
        envelope = _error_envelope(
            http_status=404,
            code="EDGAR_STATEMENTS_NOT_FOUND",
            message=str(exc),
            trace_id=trace_id,
        )
        return JSONResponse(status_code=404, content=envelope.model_dump(mode="json"))

    except EdgarMappingError as exc:
        envelope = _error_envelope(
            http_status=500,
            code="EDGAR_MAPPING_ERROR",
            message=str(exc),
            trace_id=trace_id,
            details=getattr(exc, "details", None),
        )
        return JSONResponse(status_code=500, content=envelope.model_dump(mode="json"))

    except EdgarIngestionError as exc:
        envelope = _error_envelope(
            http_status=502,
            code="EDGAR_UPSTREAM_ERROR",
            message=str(exc),
            trace_id=trace_id,
            details=getattr(exc, "details", None),
        )
        return JSONResponse(status_code=502, content=envelope.model_dump(mode="json"))

    except Exception as exc:  # pragma: no cover
        logger.exception(
            "edgar.api.get_derived_metrics_timeseries.unhandled",
            extra={"ciks": normalized_ciks, "trace_id": trace_id},
        )
        envelope = _error_envelope(
            http_status=503,
            code="EDGAR_UNAVAILABLE",
            message="EDGAR service is temporarily unavailable.",
            trace_id=trace_id,
            details={"reason": type(exc).__name__},
        )
        return JSONResponse(status_code=503, content=envelope.model_dump(mode="json"))


# ---------------------------------------------------------------------------
# Routes: Restatements (delta + ledger)
# ---------------------------------------------------------------------------


@router.get(
    "/statements/restatements/delta",
    response_model=RestatementDeltaSuccessEnvelope | ErrorEnvelope,
    status_code=status.HTTP_200_OK,
    responses=cast("dict[int | str, dict[str, Any]]", BaseRouter.std_error_responses()),
    summary="Get restatement delta between two statement versions",
    description=(
        "Compute per-metric restatement deltas between two normalized statement "
        "versions for a given (cik, statement_type, fiscal_year, fiscal_period) "
        "identity. The delta is expressed as old/new/diff per canonical metric."
    ),
)
async def get_restatement_delta(
    request: Request,
    response: Response,
    controller: Annotated[EdgarController, Depends(get_edgar_controller)],
    cik: Annotated[
        str,
        Query(
            description="Company CIK as digits (no leading 'CIK' prefix).",
            examples=["0000320193"],
        ),
    ],
    statement_type: Annotated[
        str,
        Query(
            description=(
                "Statement type " "(INCOME_STATEMENT, BALANCE_SHEET, CASH_FLOW_STATEMENT)."
            ),
            examples=["INCOME_STATEMENT"],
        ),
    ],
    fiscal_year: Annotated[
        int,
        Query(
            ge=1,
            description="Fiscal year for the statement identity (e.g., 2024).",
        ),
    ],
    fiscal_period: Annotated[
        str,
        Query(
            description="Fiscal period code (e.g., FY, Q1, Q2, Q3, Q4).",
            examples=["FY"],
        ),
    ],
    from_version_sequence: Annotated[
        int,
        Query(
            ge=1,
            description="Lower-bound version sequence (inclusive).",
            examples=[1],
        ),
    ],
    to_version_sequence: Annotated[
        int,
        Query(
            ge=1,
            description="Upper-bound version sequence (inclusive).",
            examples=[2],
        ),
    ],
) -> RestatementDeltaSuccessEnvelope | ErrorEnvelope | JSONResponse:
    """Get a restatement delta between two statement versions."""
    del request
    trace_id = response.headers.get("X-Request-ID")

    # Normalize and validate CIK.
    try:
        normalized_cik = _normalize_cik(cik)
    except HTTPException as exc:
        response.status_code = exc.status_code
        return _error_envelope(
            http_status=exc.status_code,
            code="VALIDATION_ERROR",
            message=str(exc.detail),
            trace_id=trace_id,
            details={"cik": cik},
        )

    # Parse enums manually so invalid values return 400 envelopes, not 422.
    try:
        typed_statement_type = StatementType(statement_type)
    except ValueError:
        envelope = _error_envelope(
            http_status=400,
            code="VALIDATION_ERROR",
            message="Invalid statement_type.",
            trace_id=trace_id,
            details={"statement_type": statement_type},
        )
        return JSONResponse(status_code=400, content=envelope.model_dump(mode="json"))

    try:
        typed_fiscal_period = FiscalPeriod(fiscal_period)
    except ValueError:
        envelope = _error_envelope(
            http_status=400,
            code="VALIDATION_ERROR",
            message="Invalid fiscal_period.",
            trace_id=trace_id,
            details={"fiscal_period": fiscal_period},
        )
        return JSONResponse(status_code=400, content=envelope.model_dump(mode="json"))

    # Basic version ordering validation.
    if from_version_sequence > to_version_sequence:
        response.status_code = status.HTTP_400_BAD_REQUEST
        return _error_envelope(
            http_status=400,
            code="VALIDATION_ERROR",
            message="from_version_sequence must be <= to_version_sequence.",
            trace_id=trace_id,
            details={
                "from_version_sequence": from_version_sequence,
                "to_version_sequence": to_version_sequence,
            },
        )

    logger.info(
        "edgar.api.get_restatement_delta.start",
        extra={
            "cik": normalized_cik,
            "statement_type": typed_statement_type.value,
            "fiscal_year": fiscal_year,
            "fiscal_period": typed_fiscal_period.value,
            "from_version_sequence": from_version_sequence,
            "to_version_sequence": to_version_sequence,
            "trace_id": trace_id,
        },
    )

    try:
        dto = await controller.compute_restatement_delta(
            cik=normalized_cik,
            statement_type=typed_statement_type,
            fiscal_year=fiscal_year,
            fiscal_period=typed_fiscal_period,
            from_version_sequence=from_version_sequence,
            to_version_sequence=to_version_sequence,
        )

        result = presenter.present_restatement_delta(dto=dto, trace_id=trace_id)
        body = _apply_present_result(response, result)

        logger.info(
            "edgar.api.get_restatement_delta.success",
            extra={
                "cik": normalized_cik,
                "statement_type": typed_statement_type.value,
                "fiscal_year": fiscal_year,
                "fiscal_period": typed_fiscal_period.value,
                "from_version_sequence": from_version_sequence,
                "to_version_sequence": to_version_sequence,
                "trace_id": trace_id,
            },
        )

        return cast(RestatementDeltaSuccessEnvelope, body)

    except EdgarNotFound as exc:
        envelope = _error_envelope(
            http_status=404,
            code="EDGAR_STATEMENTS_NOT_FOUND",
            message=str(exc),
            trace_id=trace_id,
        )
        return JSONResponse(status_code=404, content=envelope.model_dump(mode="json"))

    except EdgarMappingError as exc:
        envelope = _error_envelope(
            http_status=500,
            code="EDGAR_MAPPING_ERROR",
            message=str(exc),
            trace_id=trace_id,
            details=getattr(exc, "details", None),
        )
        return JSONResponse(status_code=500, content=envelope.model_dump(mode="json"))

    except EdgarIngestionError as exc:
        envelope = _error_envelope(
            http_status=502,
            code="EDGAR_UPSTREAM_ERROR",
            message=str(exc),
            trace_id=trace_id,
            details=getattr(exc, "details", None),
        )
        return JSONResponse(status_code=502, content=envelope.model_dump(mode="json"))

    except Exception as exc:  # pragma: no cover - defensive
        logger.exception(
            "edgar.api.get_restatement_delta.unhandled",
            extra={
                "cik": normalized_cik,
                "trace_id": trace_id,
            },
        )
        envelope = _error_envelope(
            http_status=503,
            code="EDGAR_UNAVAILABLE",
            message="EDGAR service is temporarily unavailable.",
            trace_id=trace_id,
            details={"reason": type(exc).__name__},
        )
        return JSONResponse(status_code=503, content=envelope.model_dump(mode="json"))


@router.get(
    "/statements/restatements/ledger",
    response_model=SuccessEnvelope[RestatementLedgerHTTP] | ErrorEnvelope,
    status_code=status.HTTP_200_OK,
    responses=cast("dict[int | str, dict[str, Any]]", BaseRouter.std_error_responses()),
    summary="Get restatement ledger for a statement identity",
    description=(
        "Return the restatement ledger for a given (cik, statement_type, fiscal_year, "
        "fiscal_period) identity. The ledger consists of ordered hops between "
        "adjacent statement versions with per-hop summaries and optional per-metric "
        "deltas."
    ),
)
async def get_restatement_ledger(
    request: Request,
    response: Response,
    controller: Annotated[EdgarController, Depends(get_edgar_controller)],
    cik: Annotated[
        str,
        Query(
            description="Company CIK as digits (no leading 'CIK' prefix).",
            examples=["0000320193"],
        ),
    ],
    statement_type: Annotated[
        str,
        Query(
            description=(
                "Statement type " "(INCOME_STATEMENT, BALANCE_SHEET, CASH_FLOW_STATEMENT)."
            ),
            examples=["INCOME_STATEMENT"],
        ),
    ],
    fiscal_year: Annotated[
        int,
        Query(
            ge=1,
            description="Fiscal year for the ledger identity.",
        ),
    ],
    fiscal_period: Annotated[
        str,
        Query(
            description="Fiscal period code (e.g., FY, Q1, Q2, Q3, Q4).",
            examples=["FY"],
        ),
    ],
) -> SuccessEnvelope[RestatementLedgerHTTP] | ErrorEnvelope | JSONResponse:
    """Get the restatement ledger for a statement identity."""
    del request
    trace_id = response.headers.get("X-Request-ID")

    # Normalize and validate CIK.
    try:
        normalized_cik = _normalize_cik(cik)
    except HTTPException as exc:
        response.status_code = exc.status_code
        return _error_envelope(
            http_status=exc.status_code,
            code="VALIDATION_ERROR",
            message=str(exc.detail),
            trace_id=trace_id,
            details={"cik": cik},
        )

    # Parse enums manually to produce 400 envelopes on invalid values.
    try:
        typed_statement_type = StatementType(statement_type)
    except ValueError:
        envelope = _error_envelope(
            http_status=400,
            code="VALIDATION_ERROR",
            message="Invalid statement_type.",
            trace_id=trace_id,
            details={"statement_type": statement_type},
        )
        return JSONResponse(status_code=400, content=envelope.model_dump(mode="json"))

    try:
        typed_fiscal_period = FiscalPeriod(fiscal_period)
    except ValueError:
        envelope = _error_envelope(
            http_status=400,
            code="VALIDATION_ERROR",
            message="Invalid fiscal_period.",
            trace_id=trace_id,
            details={"fiscal_period": fiscal_period},
        )
        return JSONResponse(status_code=400, content=envelope.model_dump(mode="json"))

    logger.info(
        "edgar.api.get_restatement_ledger.start",
        extra={
            "cik": normalized_cik,
            "statement_type": typed_statement_type.value,
            "fiscal_year": fiscal_year,
            "fiscal_period": typed_fiscal_period.value,
            "trace_id": trace_id,
        },
    )

    try:
        dto = await controller.get_restatement_ledger(
            cik=normalized_cik,
            statement_type=typed_statement_type,
            fiscal_year=fiscal_year,
            fiscal_period=typed_fiscal_period,
        )

        result = presenter.present_restatement_ledger(dto=dto, trace_id=trace_id)
        body = _apply_present_result(response, result)

        logger.info(
            "edgar.api.get_restatement_ledger.success",
            extra={
                "cik": normalized_cik,
                "statement_type": typed_statement_type.value,
                "fiscal_year": fiscal_year,
                "fiscal_period": typed_fiscal_period.value,
                "trace_id": trace_id,
            },
        )

        return cast(SuccessEnvelope[RestatementLedgerHTTP], body)

    except EdgarNotFound as exc:
        envelope = _error_envelope(
            http_status=404,
            code="EDGAR_STATEMENTS_NOT_FOUND",
            message=str(exc),
            trace_id=trace_id,
        )
        return JSONResponse(status_code=404, content=envelope.model_dump(mode="json"))

    except EdgarMappingError as exc:
        envelope = _error_envelope(
            http_status=500,
            code="EDGAR_MAPPING_ERROR",
            message=str(exc),
            trace_id=trace_id,
            details=getattr(exc, "details", None),
        )
        return JSONResponse(status_code=500, content=envelope.model_dump(mode="json"))

    except EdgarIngestionError as exc:
        envelope = _error_envelope(
            http_status=502,
            code="EDGAR_UPSTREAM_ERROR",
            message=str(exc),
            trace_id=trace_id,
            details=getattr(exc, "details", None),
        )
        return JSONResponse(status_code=502, content=envelope.model_dump(mode="json"))

    except Exception as exc:  # pragma: no cover - defensive
        logger.exception(
            "edgar.api.get_restatement_ledger.unhandled",
            extra={"cik": normalized_cik, "trace_id": trace_id},
        )
        envelope = _error_envelope(
            http_status=503,
            code="EDGAR_UNAVAILABLE",
            message="EDGAR service is temporarily unavailable.",
            trace_id=trace_id,
            details={"reason": type(exc).__name__},
        )
        return JSONResponse(status_code=503, content=envelope.model_dump(mode="json"))


@router.get(
    "/companies/{cik}/statements/restatement-timeline",
    response_model=SuccessEnvelope[RestatementMetricTimelineHTTP] | ErrorEnvelope,
    status_code=status.HTTP_200_OK,
    responses=cast("dict[int | str, dict[str, Any]]", BaseRouter.std_error_responses()),
    summary="Get restatement metric timeline for a statement identity",
    description=(
        "Return a hop-aligned restatement metric timeline for a given "
        "(cik, statement_type, fiscal_year, fiscal_period) identity. "
        "The timeline projects the restatement ledger into per-metric "
        "time series of absolute deltas and aggregate severity, suitable "
        "for modeling and quantitative analysis."
    ),
)
async def get_restatement_timeline(
    request: Request,
    response: Response,
    controller: Annotated[EdgarController, Depends(get_edgar_controller)],
    cik: Annotated[
        str,
        Path(
            description="Company CIK as digits (no leading 'CIK' prefix).",
            examples=["0000320193"],
        ),
    ],
    statement_type: Annotated[
        str,
        Query(
            description=(
                "Statement type " "(INCOME_STATEMENT, BALANCE_SHEET, CASH_FLOW_STATEMENT)."
            ),
            examples=["INCOME_STATEMENT"],
        ),
    ],
    fiscal_year: Annotated[
        int,
        Query(
            ge=1,
            description="Fiscal year for the statement identity.",
        ),
    ],
    fiscal_period: Annotated[
        str,
        Query(
            description="Fiscal period code (e.g., FY, Q1, Q2, Q3, Q4).",
            examples=["FY"],
        ),
    ],
) -> SuccessEnvelope[RestatementMetricTimelineHTTP] | ErrorEnvelope | JSONResponse:
    """Get the restatement metric timeline for a statement identity."""
    del request
    trace_id = response.headers.get("X-Request-ID")

    # Normalize and validate CIK.
    try:
        normalized_cik = _normalize_cik(cik)
    except HTTPException as exc:
        response.status_code = exc.status_code
        return _error_envelope(
            http_status=exc.status_code,
            code="VALIDATION_ERROR",
            message=str(exc.detail),
            trace_id=trace_id,
            details={"cik": cik},
        )

    # Parse enums manually to produce 400 envelopes on invalid values.
    try:
        typed_statement_type = StatementType(statement_type)
    except ValueError:
        envelope = _error_envelope(
            http_status=400,
            code="VALIDATION_ERROR",
            message="Invalid statement_type.",
            trace_id=trace_id,
            details={"statement_type": statement_type},
        )
        return JSONResponse(status_code=400, content=envelope.model_dump(mode="json"))

    try:
        typed_fiscal_period = FiscalPeriod(fiscal_period)
    except ValueError:
        envelope = _error_envelope(
            http_status=400,
            code="VALIDATION_ERROR",
            message="Invalid fiscal_period.",
            trace_id=trace_id,
            details={"fiscal_period": fiscal_period},
        )
        return JSONResponse(status_code=400, content=envelope.model_dump(mode="json"))

    logger.info(
        "edgar.api.get_restatement_timeline.start",
        extra={
            "cik": normalized_cik,
            "statement_type": typed_statement_type.value,
            "fiscal_year": fiscal_year,
            "fiscal_period": typed_fiscal_period.value,
            "trace_id": trace_id,
        },
    )

    try:
        dto = await controller.get_restatement_timeline(
            cik=normalized_cik,
            statement_type=typed_statement_type,
            fiscal_year=fiscal_year,
            fiscal_period=typed_fiscal_period,
        )

        result = presenter.present_restatement_timeline(dto=dto, trace_id=trace_id)
        body = _apply_present_result(response, result)

        logger.info(
            "edgar.api.get_restatement_timeline.success",
            extra={
                "cik": normalized_cik,
                "statement_type": typed_statement_type.value,
                "fiscal_year": fiscal_year,
                "fiscal_period": typed_fiscal_period.value,
                "trace_id": trace_id,
            },
        )

        return cast(SuccessEnvelope[RestatementMetricTimelineHTTP], body)

    except EdgarNotFound as exc:
        envelope = _error_envelope(
            http_status=404,
            code="EDGAR_STATEMENTS_NOT_FOUND",
            message=str(exc),
            trace_id=trace_id,
        )
        return JSONResponse(status_code=404, content=envelope.model_dump(mode="json"))

    except EdgarMappingError as exc:
        envelope = _error_envelope(
            http_status=500,
            code="EDGAR_MAPPING_ERROR",
            message=str(exc),
            trace_id=trace_id,
            details=getattr(exc, "details", None),
        )
        return JSONResponse(status_code=500, content=envelope.model_dump(mode="json"))

    except EdgarIngestionError as exc:
        envelope = _error_envelope(
            http_status=502,
            code="EDGAR_UPSTREAM_ERROR",
            message=str(exc),
            trace_id=trace_id,
            details=getattr(exc, "details", None),
        )
        return JSONResponse(status_code=502, content=envelope.model_dump(mode="json"))

    except Exception as exc:  # pragma: no cover - defensive
        logger.exception(
            "edgar.api.get_restatement_timeline.unhandled",
            extra={"cik": normalized_cik, "trace_id": trace_id},
        )
        envelope = _error_envelope(
            http_status=503,
            code="EDGAR_UNAVAILABLE",
            message="EDGAR service is temporarily unavailable.",
            trace_id=trace_id,
            details={"reason": type(exc).__name__},
        )
        return JSONResponse(status_code=503, content=envelope.model_dump(mode="json"))


# ---------------------------------------------------------------------------
# Routes: Data Quality (DQ) – statement scope
# ---------------------------------------------------------------------------


@router.post(
    "/companies/{cik}/statements/dq/run",
    response_model=SuccessEnvelope[RunStatementDQResultHTTP] | ErrorEnvelope,
    status_code=status.HTTP_200_OK,
    responses=cast("dict[int | str, dict[str, Any]]", BaseRouter.std_error_responses()),
    summary="Run data-quality checks for a normalized statement",
    description=(
        "Execute the EDGAR data-quality engine for a specific normalized "
        "statement version and persist the resulting run, fact-quality flags, "
        "and anomalies. Facts must have been persisted for the statement "
        "prior to invoking this endpoint."
    ),
)
async def run_statement_dq(
    request: Request,
    response: Response,
    uow: Annotated[UnitOfWork, Depends(get_edgar_uow)],
    cik: Annotated[
        str,
        Path(
            description="Company CIK as digits (no leading 'CIK' prefix).",
            examples=["0000320193"],
        ),
    ],
    statement_type: Annotated[
        str,
        Query(
            description=(
                "Statement type " "(INCOME_STATEMENT, BALANCE_SHEET, CASH_FLOW_STATEMENT)."
            ),
            examples=["INCOME_STATEMENT"],
        ),
    ],
    fiscal_year: Annotated[
        int,
        Query(
            ge=1,
            description="Fiscal year for the statement identity (>= 1).",
            examples=[2024],
        ),
    ],
    fiscal_period: Annotated[
        str,
        Query(
            description="Fiscal period code (e.g., FY, Q1, Q2, Q3, Q4).",
            examples=["FY"],
        ),
    ],
    version_sequence: Annotated[
        int,
        Query(
            ge=1,
            description="Version sequence number for this statement identity (>= 1).",
            examples=[1],
        ),
    ],
    rule_set_version: Annotated[
        str,
        Query(
            ...,
            description="Rule-set version identifier to use for this DQ run.",
        ),
    ],
    scope_type: Annotated[
        str,
        Query(
            ...,
            description="DQ scope type (e.g., STATEMENT_ONLY, STATEMENT_WITH_HISTORY).",
        ),
    ],
    history_lookback: Annotated[
        int,
        Query(
            ...,
            ge=1,
            description=(
                "Number of historical periods to inspect for history-based rules "
                "(e.g., HISTORY_SPIKE)."
            ),
        ),
    ],
) -> SuccessEnvelope[RunStatementDQResultHTTP] | ErrorEnvelope | JSONResponse:
    """Trigger a DQ run for a specific statement version."""
    del request  # reserved for future auth/feature flags
    trace_id = response.headers.get("X-Request-ID")
    normalized_cik = _normalize_cik(cik)

    # Manual enum parsing → 400 envelopes instead of FastAPI 422.
    try:
        typed_statement_type = StatementType(statement_type)
    except ValueError:
        error = _error_envelope(
            http_status=400,
            code="VALIDATION_ERROR",
            message="Invalid statement_type.",
            trace_id=trace_id,
            details={"statement_type": statement_type},
        )
        return JSONResponse(status_code=400, content=error.model_dump(mode="json"))

    try:
        typed_fiscal_period = FiscalPeriod(fiscal_period)
    except ValueError:
        error = _error_envelope(
            http_status=400,
            code="VALIDATION_ERROR",
            message="Invalid fiscal_period.",
            trace_id=trace_id,
            details={"fiscal_period": fiscal_period},
        )
        return JSONResponse(status_code=400, content=error.model_dump(mode="json"))

    logger.info(
        "edgar.api.run_statement_dq.start",
        extra={
            "cik": normalized_cik,
            "statement_type": typed_statement_type.value,
            "fiscal_year": fiscal_year,
            "fiscal_period": typed_fiscal_period.value,
            "version_sequence": version_sequence,
            "rule_set_version": rule_set_version,
            "scope_type": scope_type,
            "history_lookback": history_lookback,
            "trace_id": trace_id,
        },
    )

    use_case = RunStatementDQUseCase(uow=uow)

    try:
        req = RunStatementDQRequest(
            cik=normalized_cik,
            statement_type=typed_statement_type,
            fiscal_year=fiscal_year,
            fiscal_period=typed_fiscal_period,
            version_sequence=version_sequence,
            rule_set_version=rule_set_version,
            scope_type=scope_type,
            history_lookback=history_lookback,
        )

        result_dto = await use_case.execute(req)
        envelope = present_run_statement_dq(result_dto)

        logger.info(
            "edgar.api.run_statement_dq.success",
            extra={
                "cik": normalized_cik,
                "statement_type": typed_statement_type.value,
                "fiscal_year": fiscal_year,
                "fiscal_period": typed_fiscal_period.value,
                "version_sequence": version_sequence,
                "dq_run_id": str(envelope.data.dq_run_id),
                "max_severity": envelope.data.max_severity,
                "facts_evaluated": envelope.data.facts_evaluated,
                "anomaly_count": envelope.data.anomaly_count,
                "trace_id": trace_id,
            },
        )

        return envelope

    except EdgarNotFound as exc:
        error = _error_envelope(
            http_status=404,
            code="EDGAR_STATEMENT_NOT_FOUND",
            message=str(exc),
            trace_id=trace_id,
        )
        return JSONResponse(status_code=404, content=error.model_dump(mode="json"))

    except EdgarMappingError as exc:
        error = _error_envelope(
            http_status=500,
            code="EDGAR_MAPPING_ERROR",
            message=str(exc),
            trace_id=trace_id,
            details=getattr(exc, "details", None),
        )
        return JSONResponse(status_code=500, content=error.model_dump(mode="json"))

    except EdgarIngestionError as exc:
        error = _error_envelope(
            http_status=502,
            code="EDGAR_UPSTREAM_ERROR",
            message=str(exc),
            trace_id=trace_id,
            details=getattr(exc, "details", None),
        )
        return JSONResponse(status_code=502, content=error.model_dump(mode="json"))

    except Exception as exc:  # pragma: no cover - defensive
        logger.exception(
            "edgar.api.run_statement_dq.unhandled",
            extra={
                "cik": normalized_cik,
                "statement_type": typed_statement_type.value,
                "fiscal_year": fiscal_year,
                "fiscal_period": typed_fiscal_period.value,
                "version_sequence": version_sequence,
                "trace_id": trace_id,
            },
        )
        error = _error_envelope(
            http_status=503,
            code="EDGAR_UNAVAILABLE",
            message="DQ service is temporarily unavailable.",
            trace_id=trace_id,
            details={"reason": type(exc).__name__},
        )
        return JSONResponse(status_code=503, content=error.model_dump(mode="json"))


@router.get(
    "/companies/{cik}/statements/dq/overlay",
    response_model=SuccessEnvelope[StatementDQOverlayHTTP] | ErrorEnvelope,
    status_code=status.HTTP_200_OK,
    responses=cast("dict[int | str, dict[str, Any]]", BaseRouter.std_error_responses()),
    summary="Get a normalized statement with DQ overlay",
    description=(
        "Return a normalized EDGAR statement combined with its fact-level "
        "data-quality overlay, including latest DQ run metadata, fact-quality "
        "flags, and anomalies."
    ),
)
async def get_statement_dq_overlay(
    request: Request,
    response: Response,
    uow: Annotated[UnitOfWork, Depends(get_edgar_uow)],
    cik: Annotated[
        str,
        Path(
            description="Company CIK as digits (no leading 'CIK' prefix).",
            examples=["0000320193"],
        ),
    ],
    statement_type: Annotated[
        str,
        Query(
            description=(
                "Statement type " "(INCOME_STATEMENT, BALANCE_SHEET, CASH_FLOW_STATEMENT)."
            ),
            examples=["INCOME_STATEMENT"],
        ),
    ],
    fiscal_year: Annotated[
        int,
        Query(
            ge=1,
            description="Fiscal year for the statement identity (>= 1).",
            examples=[2024],
        ),
    ],
    fiscal_period: Annotated[
        str,
        Query(
            description="Fiscal period code (e.g., FY, Q1, Q2, Q3, Q4).",
            examples=["FY"],
        ),
    ],
    version_sequence: Annotated[
        int,
        Query(
            ge=1,
            description="Version sequence number for this statement identity (>= 1).",
            examples=[1],
        ),
    ],
) -> SuccessEnvelope[StatementDQOverlayHTTP] | ErrorEnvelope | JSONResponse:
    """Retrieve a statement + DQ overlay for a specific statement version."""
    del request
    trace_id = response.headers.get("X-Request-ID")
    normalized_cik = _normalize_cik(cik)

    try:
        typed_statement_type = StatementType(statement_type)
    except ValueError:
        error = _error_envelope(
            http_status=400,
            code="VALIDATION_ERROR",
            message="Invalid statement_type.",
            trace_id=trace_id,
            details={"statement_type": statement_type},
        )
        return JSONResponse(status_code=400, content=error.model_dump(mode="json"))

    try:
        typed_fiscal_period = FiscalPeriod(fiscal_period)
    except ValueError:
        error = _error_envelope(
            http_status=400,
            code="VALIDATION_ERROR",
            message="Invalid fiscal_period.",
            trace_id=trace_id,
            details={"fiscal_period": fiscal_period},
        )
        return JSONResponse(status_code=400, content=error.model_dump(mode="json"))

    logger.info(
        "edgar.api.get_statement_dq_overlay.start",
        extra={
            "cik": normalized_cik,
            "statement_type": typed_statement_type.value,
            "fiscal_year": fiscal_year,
            "fiscal_period": typed_fiscal_period.value,
            "version_sequence": version_sequence,
            "trace_id": trace_id,
        },
    )

    use_case = GetStatementWithDQOverlayUseCase(uow=uow)

    try:
        req = GetStatementWithDQOverlayRequest(
            cik=normalized_cik,
            statement_type=typed_statement_type,
            fiscal_year=fiscal_year,
            fiscal_period=typed_fiscal_period,
            version_sequence=version_sequence,
        )

        overlay_dto = await use_case.execute(req)
        envelope = present_statement_dq_overlay(overlay_dto)

        logger.info(
            "edgar.api.get_statement_dq_overlay.success",
            extra={
                "cik": normalized_cik,
                "statement_type": typed_statement_type.value,
                "fiscal_year": fiscal_year,
                "fiscal_period": typed_fiscal_period.value,
                "version_sequence": version_sequence,
                "dq_run_id": (str(envelope.data.dq_run_id) if envelope.data.dq_run_id else None),
                "max_severity": envelope.data.max_severity,
                "facts_count": len(envelope.data.facts),
                "fact_quality_count": len(envelope.data.fact_quality),
                "anomalies_count": len(envelope.data.anomalies),
                "trace_id": trace_id,
            },
        )

        return envelope

    except EdgarNotFound as exc:
        error = _error_envelope(
            http_status=404,
            code="EDGAR_STATEMENT_NOT_FOUND",
            message=str(exc),
            trace_id=trace_id,
        )
        return JSONResponse(status_code=404, content=error.model_dump(mode="json"))

    except EdgarMappingError as exc:
        error = _error_envelope(
            http_status=500,
            code="EDGAR_MAPPING_ERROR",
            message=str(exc),
            trace_id=trace_id,
            details=getattr(exc, "details", None),
        )
        return JSONResponse(status_code=500, content=error.model_dump(mode="json"))

    except EdgarIngestionError as exc:
        error = _error_envelope(
            http_status=502,
            code="EDGAR_UPSTREAM_ERROR",
            message=str(exc),
            trace_id=trace_id,
            details=getattr(exc, "details", None),
        )
        return JSONResponse(status_code=502, content=error.model_dump(mode="json"))

    except Exception as exc:  # pragma: no cover - defensive
        logger.exception(
            "edgar.api.get_statement_dq_overlay.unhandled",
            extra={
                "cik": normalized_cik,
                "statement_type": typed_statement_type.value,
                "fiscal_year": fiscal_year,
                "fiscal_period": typed_fiscal_period.value,
                "version_sequence": version_sequence,
                "trace_id": trace_id,
            },
        )
        error = _error_envelope(
            http_status=503,
            code="EDGAR_UNAVAILABLE",
            message="DQ overlay service is temporarily unavailable.",
            trace_id=trace_id,
            details={"reason": type(exc).__name__},
        )
        return JSONResponse(status_code=503, content=error.model_dump(mode="json"))


# ---------------------------------------------------------------------------
# Routes: XBRL mapping override observability
# ---------------------------------------------------------------------------


@router.get(
    "/companies/{cik}/statements/overrides/trace",
    response_model=SuccessEnvelope[StatementOverrideTraceHTTP] | ErrorEnvelope,
    status_code=status.HTTP_200_OK,
    responses=cast("dict[int | str, dict[str, Any]]", BaseRouter.std_error_responses()),
    summary="Inspect XBRL mapping overrides for a statement identity",
    description=(
        "Return an override observability trace for a specific normalized "
        "statement identity, optionally filtered to a GAAP/IFRS concept, "
        "canonical metric code, and/or dimension key.\n\n"
        "The trace describes how each override rule contributed to suppression "
        "and remap behavior for the evaluated slice."
    ),
)
async def get_statement_override_trace(
    request: Request,
    response: Response,
    uow: Annotated[UnitOfWork, Depends(get_edgar_uow)],
    cik: Annotated[
        str,
        Path(
            description="Company CIK as digits.",
            examples=["0000320193"],
        ),
    ],
    statement_type: Annotated[
        str,
        Query(
            description=(
                "Statement type " "(INCOME_STATEMENT, BALANCE_SHEET, CASH_FLOW_STATEMENT)."
            ),
            examples=["INCOME_STATEMENT"],
        ),
    ],
    fiscal_year: Annotated[
        int,
        Query(
            ge=1,
            description="Fiscal year for the statement identity (>= 1).",
            examples=[2024],
        ),
    ],
    fiscal_period: Annotated[
        str,
        Query(
            description="Fiscal period code (e.g., FY, Q1, Q2, Q3, Q4).",
            examples=["FY"],
        ),
    ],
    version_sequence: Annotated[
        int,
        Query(
            ge=1,
            description="Version sequence number for this statement identity (>= 1).",
            examples=[1],
        ),
    ],
    gaap_concept: Annotated[
        str | None,
        Query(
            description=("Optional GAAP/IFRS concept filter for the trace " "(e.g. Revenues)."),
        ),
    ] = None,
    canonical_metric_code: Annotated[
        str | None,
        Query(
            description=("Optional canonical metric code filter (e.g. REVENUE, NET_INCOME)."),
        ),
    ] = None,
    dimension_key: Annotated[
        str | None,
        Query(
            description=(
                "Optional dimension key filter (e.g. segment or other dimensional slice)."
            ),
        ),
    ] = None,
) -> SuccessEnvelope[StatementOverrideTraceHTTP] | ErrorEnvelope | JSONResponse:
    """Retrieve a statement-level XBRL override observability trace."""
    del request
    trace_id = response.headers.get("X-Request-ID")
    normalized_cik = _normalize_cik(cik)

    # Manual enum parsing → 400 envelopes instead of FastAPI 422.
    try:
        typed_statement_type = StatementType(statement_type)
    except ValueError:
        error = _error_envelope(
            http_status=400,
            code="VALIDATION_ERROR",
            message="Invalid statement_type.",
            trace_id=trace_id,
            details={"statement_type": statement_type},
        )
        return JSONResponse(status_code=400, content=error.model_dump(mode="json"))

    try:
        typed_fiscal_period = FiscalPeriod(fiscal_period)
    except ValueError:
        error = _error_envelope(
            http_status=400,
            code="VALIDATION_ERROR",
            message="Invalid fiscal_period.",
            trace_id=trace_id,
            details={"fiscal_period": fiscal_period},
        )
        return JSONResponse(status_code=400, content=error.model_dump(mode="json"))

    logger.info(
        "edgar.api.get_statement_override_trace.start",
        extra={
            "cik": normalized_cik,
            "statement_type": typed_statement_type.value,
            "fiscal_year": fiscal_year,
            "fiscal_period": typed_fiscal_period.value,
            "version_sequence": version_sequence,
            "gaap_concept": gaap_concept,
            "canonical_metric_code": canonical_metric_code,
            "dimension_key": dimension_key,
            "trace_id": trace_id,
        },
    )

    use_case = GetStatementOverrideTraceUseCase(uow=uow)

    try:
        req_obj = GetStatementOverrideTraceRequest(
            cik=normalized_cik,
            statement_type=typed_statement_type,
            fiscal_year=fiscal_year,
            fiscal_period=typed_fiscal_period,
            version_sequence=version_sequence,
            gaap_concept=gaap_concept,
            canonical_metric_code=canonical_metric_code,
            dimension_key=dimension_key,
        )

        dto = await use_case.execute(req_obj)
        envelope = present_statement_override_trace(dto)

        logger.info(
            "edgar.api.get_statement_override_trace.success",
            extra={
                "cik": normalized_cik,
                "statement_type": typed_statement_type.value,
                "fiscal_year": fiscal_year,
                "fiscal_period": typed_fiscal_period.value,
                "version_sequence": version_sequence,
                "gaap_concept": gaap_concept,
                "canonical_metric_code": canonical_metric_code,
                "dimension_key": dimension_key,
                "trace_id": trace_id,
            },
        )

        return envelope

    except EdgarIngestionError as exc:
        error = _error_envelope(
            http_status=404,
            code="EDGAR_STATEMENT_NOT_FOUND",
            message=str(exc),
            trace_id=trace_id,
            details=getattr(exc, "details", None),
        )
        return JSONResponse(status_code=404, content=error.model_dump(mode="json"))

    except EdgarMappingError as exc:
        error = _error_envelope(
            http_status=500,
            code="EDGAR_MAPPING_ERROR",
            message=str(exc),
            trace_id=trace_id,
            details=getattr(exc, "details", None),
        )
        return JSONResponse(status_code=500, content=error.model_dump(mode="json"))

    except Exception as exc:  # pragma: no cover - defensive
        logger.exception(
            "edgar.api.get_statement_override_trace.unhandled",
            extra={
                "cik": normalized_cik,
                "trace_id": trace_id,
            },
        )
        error = _error_envelope(
            http_status=503,
            code="EDGAR_UNAVAILABLE",
            message="Override observability service is temporarily unavailable.",
            trace_id=trace_id,
            details={"reason": type(exc).__name__},
        )
        return JSONResponse(status_code=503, content=error.model_dump(mode="json"))
