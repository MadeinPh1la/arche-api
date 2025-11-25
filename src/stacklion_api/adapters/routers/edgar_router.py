# Copyright (c)
# SPDX-License-Identifier: MIT
"""
EDGAR Router (v1).

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
from stacklion_api.adapters.presenters.base_presenter import PresentResult
from stacklion_api.adapters.presenters.edgar_presenter import EdgarPresenter
from stacklion_api.adapters.routers.base_router import BaseRouter, PageParams
from stacklion_api.adapters.schemas.http.edgar_schemas import (
    EdgarFilingHTTP,
    EdgarStatementVersionListHTTP,
)
from stacklion_api.adapters.schemas.http.envelopes import (
    ErrorEnvelope,
    ErrorObject,
    PaginatedEnvelope,
    SuccessEnvelope,
)
from stacklion_api.application.schemas.dto.edgar import EdgarFilingDTO
from stacklion_api.dependencies.edgar import get_edgar_controller
from stacklion_api.domain.enums.edgar import FilingType, StatementType
from stacklion_api.domain.exceptions.edgar import (
    EdgarIngestionError,
    EdgarMappingError,
    EdgarNotFound,
)
from stacklion_api.infrastructure.logging.logger import get_json_logger

logger = get_json_logger(__name__)

# v1 EDGAR router
router = BaseRouter(version="v1", resource="edgar", tags=["EDGAR Filings"])
presenter = EdgarPresenter()


# --------------------------------------------------------------------------- #
# Helpers                                                                     #
# --------------------------------------------------------------------------- #


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


# --------------------------------------------------------------------------- #
# Routes: Filings                                                             #
# --------------------------------------------------------------------------- #


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


# --------------------------------------------------------------------------- #
# Routes: Statement versions                                                  #
# --------------------------------------------------------------------------- #


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
                "Whether to request long-form normalized payloads. "
                "Currently accepted but normalized_payload is always null."
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
