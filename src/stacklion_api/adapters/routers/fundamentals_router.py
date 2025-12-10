# src/stacklion_api/adapters/routers/fundamentals_router.py
# Copyright (c)
# SPDX-License-Identifier: MIT
"""Fundamentals and restatement HTTP router (v1).

Purpose:
    Expose Bloomberg-class modeling endpoints on top of normalized EDGAR
    statement payloads:

        * GET /v1/fundamentals/time-series
        * GET /v1/fundamentals/derived/time-series
        * GET /v1/fundamentals/restatement-delta
        * GET /v1/fundamentals/normalized-statements

    All endpoints:
        - Are read-only.
        - Use canonical envelopes (SuccessEnvelope / PaginatedEnvelope).
        - Rely on application-layer use cases for domain behavior.
        - Map domain/application exceptions into structured ErrorEnvelope
          responses consistent with API_STANDARDS.

Layer:
    adapters/routers

Notes:
    - This router uses BaseRouter so that versioning and resource prefixing
      (/v1/fundamentals) are consistent with the rest of the API.
    - UnitOfWork is obtained via a dedicated dependency function. For now
      this uses a no-op UnitOfWork suitable for validation / error-path
      tests; EDGAR wiring can later replace this with a real SQLAlchemy UoW.
"""

from __future__ import annotations

from datetime import date
from typing import Annotated, Any, cast

from fastapi import Depends, HTTPException, Query, Request, Response, status
from fastapi.responses import JSONResponse

from stacklion_api.adapters.dependencies.edgar_uow import get_edgar_uow
from stacklion_api.adapters.presenters.edgar_dq_presenter import present_statement_dq_overlay
from stacklion_api.adapters.presenters.fundamentals_presenter import (
    present_derived_time_series,
    present_fundamentals_time_series,
    present_normalized_statement,
    present_restatement_delta,
)
from stacklion_api.adapters.routers.base_router import BaseRouter
from stacklion_api.adapters.schemas.http.edgar_dq_schemas import StatementDQOverlayHTTP
from stacklion_api.adapters.schemas.http.envelopes import (
    ErrorEnvelope,
    ErrorObject,
    PaginatedEnvelope,
    RestatementDeltaSuccessEnvelope,
    SuccessEnvelope,
)
from stacklion_api.adapters.schemas.http.fundamentals import (
    DerivedMetricsTimeSeriesPointHTTP,
    FundamentalsTimeSeriesPointHTTP,
    NormalizedStatementViewHTTP,
)
from stacklion_api.application.uow import UnitOfWork
from stacklion_api.application.use_cases.statements.compute_restatement_delta import (
    ComputeRestatementDeltaRequest,
    ComputeRestatementDeltaUseCase,
)
from stacklion_api.application.use_cases.statements.get_derived_metrics_timeseries import (
    GetDerivedMetricsTimeSeriesRequest,
    GetDerivedMetricsTimeSeriesUseCase,
)
from stacklion_api.application.use_cases.statements.get_fundamentals_timeseries import (
    GetFundamentalsTimeSeriesRequest,
    GetFundamentalsTimeSeriesUseCase,
)
from stacklion_api.application.use_cases.statements.get_normalized_statement import (
    GetNormalizedStatementRequest,
    GetNormalizedStatementUseCase,
)
from stacklion_api.application.use_cases.statements.get_statement_with_dq_overlay import (
    GetStatementWithDQOverlayRequest,
    GetStatementWithDQOverlayUseCase,
)
from stacklion_api.domain.enums.canonical_statement_metric import CanonicalStatementMetric
from stacklion_api.domain.enums.derived_metric import DerivedMetric
from stacklion_api.domain.enums.edgar import FiscalPeriod, StatementType
from stacklion_api.domain.exceptions.edgar import (
    EdgarIngestionError,
    EdgarMappingError,
    EdgarNotFound,
)
from stacklion_api.infrastructure.logging.logger import get_json_logger

logger = get_json_logger(__name__)

# v1 Fundamentals router: /v1/fundamentals/...
router = BaseRouter(version="v1", resource="fundamentals", tags=["Fundamentals"])

# --------------------------------------------------------------------------- #
# UoW dependency – EDGAR SQLAlchemy-backed UnitOfWork                         #
# --------------------------------------------------------------------------- #


def get_uow() -> UnitOfWork:
    """FastAPI dependency yielding the EDGAR SQLAlchemy-backed UnitOfWork.

    This delegates to the shared EDGAR dependency wiring so that fundamentals
    endpoints operate on the same fact store and statement repositories as the
    EDGAR router.
    """
    return get_edgar_uow()


# --------------------------------------------------------------------------- #
# Helpers                                                                     #
# --------------------------------------------------------------------------- #


def _normalize_cik(raw: str) -> str:
    """Normalize and validate a CIK string.

    Rules:
        - Must be non-empty after trimming.
        - Must contain only digits.
    """
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
        ),
    )


# --------------------------------------------------------------------------- #
# Routes: Fundamentals time series                                            #
# --------------------------------------------------------------------------- #


@router.get(
    "/time-series",
    summary="Fundamentals time series",
    description=(
        "Return a panel-friendly fundamentals time series derived from "
        "normalized EDGAR statement payloads. The endpoint supports a CIK "
        "universe, canonical metric selection, annual/quarterly frequency, "
        "and a deterministic time window."
    ),
    # Governance requires a generic PaginatedEnvelope schema name in OpenAPI.
    response_model=PaginatedEnvelope,
    responses=cast("dict[int | str, dict[str, Any]]", BaseRouter.std_error_responses()),
)
async def get_fundamentals_time_series(
    request: Request,
    response: Response,
    uow: Annotated[UnitOfWork, Depends(get_uow)],
    ciks: Annotated[
        list[str],
        Query(
            ...,
            description=(
                "Universe of companies expressed as CIKs. Multiple CIKs can be "
                "provided via repeated query parameters (e.g., "
                "`?ciks=0000320193&ciks=0000789019`)."
            ),
        ),
    ],
    statement_type: Annotated[
        StatementType,
        Query(
            ...,
            description=(
                "Statement type to use as the source of fundamentals " "(e.g., INCOME_STATEMENT)."
            ),
        ),
    ],
    metrics: Annotated[
        list[CanonicalStatementMetric] | None,
        Query(
            description=(
                "Optional subset of canonical metrics to include. When omitted, "
                "all metrics present in the underlying normalized payloads are "
                "considered for each point."
            ),
        ),
    ] = None,
    frequency: Annotated[
        str,
        Query(
            description="Requested frequency: 'annual' (FY) or 'quarterly' (Q1–Q4).",
        ),
    ] = "annual",
    from_date: Annotated[
        date | None,
        Query(
            alias="from",
            description=(
                "Inclusive lower bound for statement_date (YYYY-MM-DD). When "
                "omitted, defaults to 1994-01-01."
            ),
        ),
    ] = None,
    to_date: Annotated[
        date | None,
        Query(
            alias="to",
            description=(
                "Inclusive upper bound for statement_date (YYYY-MM-DD). When "
                "omitted, defaults to today's date."
            ),
        ),
    ] = None,
    use_tier1_only: Annotated[
        bool,
        Query(
            description=(
                "When true and `metrics` is omitted, restrict the fundamentals "
                "time series to the Tier-1 canonical metrics for the requested "
                "statement_type, as defined by the canonical metric registry."
            ),
        ),
    ] = False,
    page: Annotated[
        int,
        Query(
            ge=1,
            description="1-based page index for pagination.",
        ),
    ] = 1,
    page_size: Annotated[
        int,
        Query(
            ge=1,
            le=200,
            description="Maximum number of items to return per page (1–200).",
        ),
    ] = 50,
) -> PaginatedEnvelope[FundamentalsTimeSeriesPointHTTP] | JSONResponse:
    """HTTP handler for /v1/fundamentals/time-series."""
    del request  # reserved for future auth/feature flags
    trace_id = response.headers.get("X-Request-ID")

    normalized_ciks = [_normalize_cik(cik) for cik in ciks]

    # HTTP-level date-window validation to satisfy E6 tests.
    if from_date and to_date and from_date > to_date:
        error = _error_envelope(
            http_status=400,
            code="VALIDATION_ERROR",
            message="from date must be <= to date.",
            trace_id=trace_id,
            details={
                "from": from_date.isoformat(),
                "to": to_date.isoformat(),
            },
        )
        return JSONResponse(status_code=400, content=error.model_dump(mode="json"))

    logger.info(
        "fundamentals.api.time_series.start",
        extra={
            "ciks": normalized_ciks,
            "statement_type": statement_type.value,
            "metrics": [m.value for m in metrics] if metrics is not None else None,
            "frequency": frequency,
            "from_date": from_date.isoformat() if from_date else None,
            "to_date": to_date.isoformat() if to_date else None,
            "use_tier1_only": use_tier1_only,
            "page": page,
            "page_size": page_size,
            "trace_id": trace_id,
        },
    )

    use_case = GetFundamentalsTimeSeriesUseCase(uow=uow)

    try:
        req = GetFundamentalsTimeSeriesRequest(
            ciks=normalized_ciks,
            statement_type=statement_type,
            metrics=tuple(metrics) if metrics is not None else None,
            frequency=frequency,
            from_date=from_date,
            to_date=to_date,
            use_tier1_only=use_tier1_only,
        )

        series = await use_case.execute(req)

        envelope = present_fundamentals_time_series(
            points=series,
            page=page,
            page_size=page_size,
        )

        logger.info(
            "fundamentals.api.time_series.success",
            extra={
                "ciks": normalized_ciks,
                "statement_type": statement_type.value,
                "frequency": frequency,
                "count": len(envelope.items),
                "total": envelope.total,
                "page": envelope.page,
                "page_size": envelope.page_size,
                "trace_id": trace_id,
            },
        )
        return envelope

    except EdgarNotFound as exc:
        error = _error_envelope(
            http_status=404,
            code="FUNDAMENTALS_NOT_FOUND",
            message=str(exc),
            trace_id=trace_id,
        )
        return JSONResponse(status_code=404, content=error.model_dump(mode="json"))

    except EdgarMappingError as exc:
        error = _error_envelope(
            http_status=400,
            code="EDGAR_MAPPING_ERROR",
            message=str(exc),
            trace_id=trace_id,
            details=getattr(exc, "details", None),
        )
        return JSONResponse(status_code=400, content=error.model_dump(mode="json"))

    except EdgarIngestionError as exc:
        # Upstream ingestion/availability problem – surface as 502.
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
            "fundamentals.api.time_series.unhandled",
            extra={"trace_id": trace_id},
        )
        error = _error_envelope(
            http_status=500,
            code="INTERNAL_ERROR",
            message="Fundamentals time series endpoint failed unexpectedly.",
            trace_id=trace_id,
            details={"reason": type(exc).__name__},
        )
        return JSONResponse(status_code=500, content=error.model_dump(mode="json"))


# --------------------------------------------------------------------------- #
# Routes: Derived metrics time series                                         #
# --------------------------------------------------------------------------- #


@router.get(
    "/derived/time-series",
    summary="Derived metrics time series",
    description=(
        "Return a panel-friendly derived metrics time series (margins, growth, "
        "cash flows, returns) computed from normalized EDGAR statement "
        "payloads. The endpoint supports a CIK universe, derived metric "
        "selection, annual/quarterly frequency, and a deterministic time window."
    ),
    response_model=PaginatedEnvelope,
    responses=cast("dict[int | str, dict[str, Any]]", BaseRouter.std_error_responses()),
)
async def get_derived_metrics_time_series(
    request: Request,
    response: Response,
    uow: Annotated[UnitOfWork, Depends(get_uow)],
    ciks: Annotated[
        list[str],
        Query(
            ...,
            description=(
                "Universe of companies expressed as CIKs. Multiple CIKs can be "
                "provided via repeated query parameters (e.g., "
                "`?ciks=0000320193&ciks=0000789019`)."
            ),
        ),
    ],
    statement_type: Annotated[
        StatementType,
        Query(
            ...,
            description=(
                "Statement type to use as the primary source for fundamentals "
                "(e.g., INCOME_STATEMENT, BALANCE_SHEET)."
            ),
        ),
    ],
    metrics: Annotated[
        list[DerivedMetric] | None,
        Query(
            description=(
                "Optional subset of derived metrics to include (e.g., "
                "GROSS_MARGIN, ROE). When omitted, all E7 metrics are "
                "attempted and only successfully computed metrics are "
                "returned per point."
            ),
        ),
    ] = None,
    frequency: Annotated[
        str,
        Query(
            description="Requested frequency: 'annual' (FY) or 'quarterly' (Q1–Q4).",
        ),
    ] = "annual",
    from_date: Annotated[
        date | None,
        Query(
            alias="from",
            description=(
                "Inclusive lower bound for statement_date (YYYY-MM-DD). When "
                "omitted, defaults to 1994-01-01."
            ),
        ),
    ] = None,
    to_date: Annotated[
        date | None,
        Query(
            alias="to",
            description=(
                "Inclusive upper bound for statement_date (YYYY-MM-DD). When "
                "omitted, defaults to today's date."
            ),
        ),
    ] = None,
    page: Annotated[
        int,
        Query(
            ge=1,
            description="1-based page index for pagination.",
        ),
    ] = 1,
    page_size: Annotated[
        int,
        Query(
            ge=1,
            le=200,
            description="Maximum number of items to return per page (1–200).",
        ),
    ] = 50,
) -> PaginatedEnvelope[DerivedMetricsTimeSeriesPointHTTP] | JSONResponse:
    """HTTP handler for /v1/fundamentals/derived/time-series."""
    del request  # reserved for future auth/feature flags
    trace_id = response.headers.get("X-Request-ID")

    normalized_ciks = [_normalize_cik(cik) for cik in ciks]

    if from_date and to_date and from_date > to_date:
        error = _error_envelope(
            http_status=400,
            code="VALIDATION_ERROR",
            message="from date must be <= to date.",
            trace_id=trace_id,
            details={
                "from": from_date.isoformat(),
                "to": to_date.isoformat(),
            },
        )
        return JSONResponse(status_code=400, content=error.model_dump(mode="json"))

    logger.info(
        "fundamentals.api.derived_time_series.start",
        extra={
            "ciks": normalized_ciks,
            "statement_type": statement_type.value,
            "metrics": [m.value for m in metrics] if metrics is not None else None,
            "frequency": frequency,
            "from_date": from_date.isoformat() if from_date else None,
            "to_date": to_date.isoformat() if to_date else None,
            "page": page,
            "page_size": page_size,
            "trace_id": trace_id,
        },
    )

    use_case = GetDerivedMetricsTimeSeriesUseCase(uow=uow)

    try:
        req = GetDerivedMetricsTimeSeriesRequest(
            ciks=normalized_ciks,
            statement_type=statement_type,
            metrics=tuple(metrics) if metrics is not None else None,
            frequency=frequency,
            from_date=from_date,
            to_date=to_date,
        )

        series = await use_case.execute(req)

        envelope = present_derived_time_series(
            points=series,
            page=page,
            page_size=page_size,
        )

        logger.info(
            "fundamentals.api.derived_time_series.success",
            extra={
                "ciks": normalized_ciks,
                "statement_type": statement_type.value,
                "frequency": frequency,
                "count": len(envelope.items),
                "total": envelope.total,
                "page": envelope.page,
                "page_size": envelope.page_size,
                "trace_id": trace_id,
            },
        )
        return envelope

    except EdgarNotFound as exc:
        error = _error_envelope(
            http_status=404,
            code="FUNDAMENTALS_NOT_FOUND",
            message=str(exc),
            trace_id=trace_id,
        )
        return JSONResponse(status_code=404, content=error.model_dump(mode="json"))

    except EdgarMappingError as exc:
        error = _error_envelope(
            http_status=400,
            code="EDGAR_MAPPING_ERROR",
            message=str(exc),
            trace_id=trace_id,
            details=getattr(exc, "details", None),
        )
        return JSONResponse(status_code=400, content=error.model_dump(mode="json"))

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
            "fundamentals.api.derived_time_series.unhandled",
            extra={"trace_id": trace_id},
        )
        error = _error_envelope(
            http_status=500,
            code="INTERNAL_ERROR",
            message="Derived metrics time series endpoint failed unexpectedly.",
            trace_id=trace_id,
            details={"reason": type(exc).__name__},
        )
        return JSONResponse(status_code=500, content=error.model_dump(mode="json"))


# --------------------------------------------------------------------------- #
# Routes: Restatement delta                                                   #
# --------------------------------------------------------------------------- #


@router.get(
    "/restatement-delta",
    summary="Restatement delta for a single statement",
    description=(
        "Compute a version-over-version restatement delta for a single "
        "normalized EDGAR statement, returning per-metric changes between "
        "two version sequences."
    ),
    response_model=RestatementDeltaSuccessEnvelope | ErrorEnvelope,
    responses=cast("dict[int | str, dict[str, Any]]", BaseRouter.std_error_responses()),
)
async def get_restatement_delta(
    request: Request,
    response: Response,
    uow: Annotated[UnitOfWork, Depends(get_uow)],
    cik: Annotated[
        str,
        Query(
            ...,
            description="Central Index Key for the filer.",
        ),
    ],
    statement_type: Annotated[
        StatementType,
        Query(
            ...,
            description="Statement type (e.g., INCOME_STATEMENT, BALANCE_SHEET).",
        ),
    ],
    fiscal_year: Annotated[
        int,
        Query(
            ...,
            ge=1,
            description="Fiscal year associated with the statement (>= 1).",
        ),
    ],
    fiscal_period: Annotated[
        FiscalPeriod,
        Query(
            ...,
            description="Fiscal period within the year (e.g., FY, Q1, Q2).",
        ),
    ],
    from_version_sequence: Annotated[
        int,
        Query(
            ...,
            ge=1,
            description="Sequence number for the 'from' (pre-restatement) version.",
        ),
    ],
    to_version_sequence: Annotated[
        int,
        Query(
            ...,
            ge=1,
            description="Sequence number for the 'to' (post-restatement) version.",
        ),
    ],
    metrics: Annotated[
        list[CanonicalStatementMetric] | None,
        Query(
            description=(
                "Optional subset of canonical metrics to consider. When omitted, "
                "all metrics present in both versions are inspected and only "
                "those that changed are returned."
            ),
        ),
    ] = None,
) -> RestatementDeltaSuccessEnvelope | ErrorEnvelope | JSONResponse:
    """HTTP handler for /v1/fundamentals/restatement-delta."""
    del request  # reserved for future auth
    trace_id = response.headers.get("X-Request-ID")
    normalized_cik = _normalize_cik(cik)

    if from_version_sequence >= to_version_sequence:
        error = _error_envelope(
            http_status=400,
            code="VALIDATION_ERROR",
            message="from_version_sequence must be < to_version_sequence.",
            trace_id=trace_id,
            details={
                "from_version_sequence": from_version_sequence,
                "to_version_sequence": to_version_sequence,
            },
        )
        return JSONResponse(status_code=400, content=error.model_dump(mode="json"))

    logger.info(
        "fundamentals.api.restatement_delta.start",
        extra={
            "cik": normalized_cik,
            "statement_type": statement_type.value,
            "fiscal_year": fiscal_year,
            "fiscal_period": fiscal_period.value,
            "from_version_sequence": from_version_sequence,
            "to_version_sequence": to_version_sequence,
            "metrics": [m.value for m in metrics] if metrics is not None else None,
            "trace_id": trace_id,
        },
    )

    use_case = ComputeRestatementDeltaUseCase(uow=uow)

    try:
        req = ComputeRestatementDeltaRequest(
            cik=normalized_cik,
            statement_type=statement_type,
            fiscal_year=fiscal_year,
            fiscal_period=fiscal_period,
            from_version_sequence=from_version_sequence,
            to_version_sequence=to_version_sequence,
            metrics=tuple(metrics) if metrics is not None else None,
        )

        result = await use_case.execute(req)

        envelope = present_restatement_delta(result=result)

        logger.info(
            "fundamentals.api.restatement_delta.success",
            extra={
                "cik": normalized_cik,
                "statement_type": statement_type.value,
                "fiscal_year": fiscal_year,
                "fiscal_period": fiscal_period.value,
                "from_version_sequence": from_version_sequence,
                "to_version_sequence": to_version_sequence,
                "metrics_count": len(envelope.data.deltas),
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
            http_status=400,
            code="EDGAR_MAPPING_ERROR",
            message=str(exc),
            trace_id=trace_id,
            details=getattr(exc, "details", None),
        )
        return JSONResponse(status_code=400, content=error.model_dump(mode="json"))

    except EdgarIngestionError as exc:
        error = _error_envelope(
            http_status=502,
            code="EDGAR_UPSTREAM_ERROR",
            message=str(exc),
            trace_id=trace_id,
            details=getattr(exc, "details", None),
        )
        return JSONResponse(status_code=502, content=error.model_dump(mode="json"))

    except Exception as exc:  # pragma: no cover
        logger.exception(
            "fundamentals.api.restatement_delta.unhandled",
            extra={"cik": normalized_cik, "trace_id": trace_id},
        )
        error = _error_envelope(
            http_status=500,
            code="INTERNAL_ERROR",
            message="Restatement delta endpoint failed unexpectedly.",
            trace_id=trace_id,
            details={"reason": type(exc).__name__},
        )
        return JSONResponse(status_code=500, content=error.model_dump(mode="json"))


# --------------------------------------------------------------------------- #
# Routes: Normalized statement with version history                           #
# --------------------------------------------------------------------------- #


@router.get(
    "/normalized-statements",
    summary="Normalized EDGAR statement with version history",
    description=(
        "Return the latest normalized EDGAR statement version for a given "
        "(CIK, statement_type, fiscal_year, fiscal_period) identity tuple, "
        "optionally including its version history."
    ),
    response_model=SuccessEnvelope[NormalizedStatementViewHTTP] | ErrorEnvelope,
    responses=cast("dict[int | str, dict[str, Any]]", BaseRouter.std_error_responses()),
)
async def get_normalized_statement(
    request: Request,
    response: Response,
    uow: Annotated[UnitOfWork, Depends(get_uow)],
    cik: Annotated[
        str,
        Query(
            ...,
            description="Central Index Key for the filer.",
        ),
    ],
    statement_type: Annotated[
        StatementType,
        Query(
            ...,
            description="Statement type (e.g., INCOME_STATEMENT, BALANCE_SHEET).",
        ),
    ],
    fiscal_year: Annotated[
        int,
        Query(
            ...,
            ge=1,
            description="Fiscal year associated with the statement (>= 1).",
        ),
    ],
    fiscal_period: Annotated[
        FiscalPeriod,
        Query(
            ...,
            description="Fiscal period within the year (e.g., FY, Q1, Q2).",
        ),
    ],
    include_version_history: Annotated[
        bool,
        Query(
            description="Whether to include full version history in the response.",
        ),
    ] = True,
) -> SuccessEnvelope[NormalizedStatementViewHTTP] | ErrorEnvelope | JSONResponse:
    """HTTP handler for /v1/fundamentals/normalized-statements."""
    del request
    trace_id = response.headers.get("X-Request-ID")
    normalized_cik = _normalize_cik(cik)

    logger.info(
        "fundamentals.api.normalized_statement.start",
        extra={
            "cik": normalized_cik,
            "statement_type": statement_type.value,
            "fiscal_year": fiscal_year,
            "fiscal_period": fiscal_period.value,
            "include_version_history": include_version_history,
            "trace_id": trace_id,
        },
    )

    use_case = GetNormalizedStatementUseCase(uow=uow)

    try:
        req = GetNormalizedStatementRequest(
            cik=normalized_cik,
            statement_type=statement_type,
            fiscal_year=fiscal_year,
            fiscal_period=fiscal_period,
            include_version_history=include_version_history,
        )

        result = await use_case.execute(req)

        envelope = present_normalized_statement(result=result)

        logger.info(
            "fundamentals.api.normalized_statement.success",
            extra={
                "cik": normalized_cik,
                "statement_type": statement_type.value,
                "fiscal_year": fiscal_year,
                "fiscal_period": fiscal_period.value,
                "include_version_history": include_version_history,
                "has_history": bool(envelope.data.version_history),
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
            http_status=400,
            code="EDGAR_MAPPING_ERROR",
            message=str(exc),
            trace_id=trace_id,
            details=getattr(exc, "details", None),
        )
        return JSONResponse(status_code=400, content=error.model_dump(mode="json"))

    except EdgarIngestionError as exc:
        error = _error_envelope(
            http_status=502,
            code="EDGAR_UPSTREAM_ERROR",
            message=str(exc),
            trace_id=trace_id,
            details=getattr(exc, "details", None),
        )
        return JSONResponse(status_code=502, content=error.model_dump(mode="json"))

    except Exception as exc:  # pragma: no cover
        logger.exception(
            "fundamentals.api.normalized_statement.unhandled",
            extra={"cik": normalized_cik, "trace_id": trace_id},
        )
        error = _error_envelope(
            http_status=500,
            code="INTERNAL_ERROR",
            message="Normalized statement endpoint failed unexpectedly.",
            trace_id=trace_id,
            details={"reason": type(exc).__name__},
        )
        return JSONResponse(status_code=500, content=error.model_dump(mode="json"))


@router.get(
    "/normalized-statements/dq-overlay",
    summary="Normalized statement with data-quality overlay",
    description=(
        "Return a normalized EDGAR statement for a given identity tuple, "
        "combined with fact-level data-quality overlay (latest DQ run, "
        "fact-quality flags, anomalies). This endpoint is a fundamentals-"
        "namespaced façade over the EDGAR DQ overlay use case."
    ),
    response_model=SuccessEnvelope[StatementDQOverlayHTTP] | ErrorEnvelope,
    responses=cast("dict[int | str, dict[str, Any]]", BaseRouter.std_error_responses()),
)
async def get_normalized_statement_dq_overlay(
    request: Request,
    response: Response,
    uow: Annotated[UnitOfWork, Depends(get_uow)],
    cik: Annotated[
        str,
        Query(
            ...,
            description="Central Index Key for the filer.",
        ),
    ],
    statement_type: Annotated[
        StatementType,
        Query(
            ...,
            description="Statement type (e.g., INCOME_STATEMENT, BALANCE_SHEET).",
        ),
    ],
    fiscal_year: Annotated[
        int,
        Query(
            ...,
            ge=1,
            description="Fiscal year associated with the statement (>= 1).",
        ),
    ],
    fiscal_period: Annotated[
        FiscalPeriod,
        Query(
            ...,
            description="Fiscal period within the year (e.g., FY, Q1, Q2).",
        ),
    ],
    version_sequence: Annotated[
        int,
        Query(
            ...,
            ge=1,
            description="Statement version sequence number to overlay.",
        ),
    ],
) -> SuccessEnvelope[StatementDQOverlayHTTP] | ErrorEnvelope | JSONResponse:
    """HTTP handler for /v1/fundamentals/normalized-statements/dq-overlay."""
    del request
    trace_id = response.headers.get("X-Request-ID")
    normalized_cik = _normalize_cik(cik)

    logger.info(
        "fundamentals.api.normalized_statement_dq_overlay.start",
        extra={
            "cik": normalized_cik,
            "statement_type": statement_type.value,
            "fiscal_year": fiscal_year,
            "fiscal_period": fiscal_period.value,
            "version_sequence": version_sequence,
            "trace_id": trace_id,
        },
    )

    use_case = GetStatementWithDQOverlayUseCase(uow=uow)

    try:
        req = GetStatementWithDQOverlayRequest(
            cik=normalized_cik,
            statement_type=statement_type,
            fiscal_year=fiscal_year,
            fiscal_period=fiscal_period,
            version_sequence=version_sequence,
        )

        overlay = await use_case.execute(req)
        envelope = present_statement_dq_overlay(overlay)

        logger.info(
            "fundamentals.api.normalized_statement_dq_overlay.success",
            extra={
                "cik": normalized_cik,
                "statement_type": statement_type.value,
                "fiscal_year": fiscal_year,
                "fiscal_period": fiscal_period.value,
                "version_sequence": version_sequence,
                "dq_run_id": str(envelope.data.dq_run_id) if envelope.data.dq_run_id else None,
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
            http_status=400,
            code="EDGAR_MAPPING_ERROR",
            message=str(exc),
            trace_id=trace_id,
            details=getattr(exc, "details", None),
        )
        return JSONResponse(status_code=400, content=error.model_dump(mode="json"))

    except EdgarIngestionError as exc:
        error = _error_envelope(
            http_status=502,
            code="EDGAR_UPSTREAM_ERROR",
            message=str(exc),
            trace_id=trace_id,
            details=getattr(exc, "details", None),
        )
        return JSONResponse(status_code=502, content=error.model_dump(mode="json"))

    except Exception as exc:  # pragma: no cover
        logger.exception(
            "fundamentals.api.normalized_statement_dq_overlay.unhandled",
            extra={
                "cik": normalized_cik,
                "statement_type": statement_type.value,
                "fiscal_year": fiscal_year,
                "fiscal_period": fiscal_period.value,
                "version_sequence": version_sequence,
                "trace_id": trace_id,
            },
        )
        error = _error_envelope(
            http_status=500,
            code="INTERNAL_ERROR",
            message="Normalized statement DQ overlay endpoint failed unexpectedly.",
            trace_id=trace_id,
            details={"reason": type(exc).__name__},
        )
        return JSONResponse(status_code=500, content=error.model_dump(mode="json"))
