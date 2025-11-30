# src/stacklion_api/adapters/routers/views_router.py
# Copyright (c)
# SPDX-License-Identifier: MIT
"""Metric Views Router (v1).

Synopsis:
    HTTP surface for metric bundles ("views") built on top of EDGAR-derived
    metrics time series.

Endpoints (all under /v1/views):
    - GET /v1/views/metrics
        → SuccessEnvelope with the catalog of registered metric views.
    - GET /v1/views/metrics/{bundle_code}
        → SuccessEnvelope with derived metrics time-series points for the
          given bundle.

Design:
    * Router handles HTTP validation and error mapping to envelopes.
    * Delegates to EdgarController.get_derived_metrics_timeseries with an
      optional ``bundle_code`` argument.
    * Uses the same presenter and HTTP schemas as the EDGAR derived-metrics
      time-series endpoint for consistency.
"""

from __future__ import annotations

from datetime import date
from typing import Annotated, Any, cast

from fastapi import Depends, HTTPException, Path, Query, Request, Response, status
from fastapi.responses import JSONResponse

from stacklion_api.adapters.controllers.edgar_controller import EdgarController
from stacklion_api.adapters.presenters.base_presenter import PresentResult
from stacklion_api.adapters.presenters.edgar_presenter import EdgarPresenter
from stacklion_api.adapters.routers.base_router import BaseRouter
from stacklion_api.adapters.schemas.http.edgar_schemas import (
    EdgarDerivedMetricsTimeSeriesHTTP,
    MetricViewsCatalogHTTP,
)
from stacklion_api.adapters.schemas.http.envelopes import (
    ErrorEnvelope,
    ErrorObject,
    SuccessEnvelope,
)
from stacklion_api.dependencies.edgar import get_edgar_controller
from stacklion_api.domain.enums.derived_metric import DerivedMetric
from stacklion_api.domain.enums.edgar import StatementType
from stacklion_api.domain.exceptions.edgar import (
    EdgarIngestionError,
    EdgarMappingError,
)
from stacklion_api.domain.services.metric_views import list_metric_views
from stacklion_api.infrastructure.logging.logger import get_json_logger

logger = get_json_logger(__name__)

# v1 Metric Views router
router = BaseRouter(version="v1", resource="views", tags=["Metric Views"])
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
        ),
    )


def _apply_present_result(response: Response, result: PresentResult[Any]) -> Any:
    """Apply presenter-controlled headers/status and return the body."""
    presenter.apply_headers(result, response)
    body = result.body
    if body is None:
        return {}
    return body


# --------------------------------------------------------------------------- #
# Routes: Metric views catalog                                                #
# --------------------------------------------------------------------------- #


@router.get(
    "/metrics",
    response_model=SuccessEnvelope[MetricViewsCatalogHTTP],
    status_code=status.HTTP_200_OK,
    responses=cast(
        "dict[int | str, dict[str, Any]]",
        BaseRouter.std_error_responses(),
    ),
    summary="List registered metric views (bundles)",
    description=(
        "Return the catalog of registered metric views (bundles) that can be "
        "used with the derived-metrics time-series endpoints. Each view "
        "represents an opinionated set of derived metrics (e.g., "
        "'core_fundamentals')."
    ),
)
async def list_metric_views_endpoint(
    request: Request,
    response: Response,
) -> SuccessEnvelope[MetricViewsCatalogHTTP]:
    """List all registered metric views."""
    del request
    trace_id = response.headers.get("X-Request-ID")

    logger.info(
        "views.api.list_metric_views.start",
        extra={
            "trace_id": trace_id,
        },
    )

    views = list_metric_views()
    result = presenter.present_metric_views_catalog(views=views, trace_id=trace_id)
    body = _apply_present_result(response, result)

    logger.info(
        "views.api.list_metric_views.success",
        extra={
            "trace_id": trace_id,
            "views_count": len(views),
            "view_codes": [v.code for v in views],
        },
    )

    return cast(SuccessEnvelope[MetricViewsCatalogHTTP], body)


# --------------------------------------------------------------------------- #
# Routes: Metric views → derived metrics time series                          #
# --------------------------------------------------------------------------- #


@router.get(
    "/metrics/{bundle_code}",
    response_model=SuccessEnvelope[EdgarDerivedMetricsTimeSeriesHTTP] | ErrorEnvelope,
    status_code=status.HTTP_200_OK,
    responses=cast(
        "dict[int | str, dict[str, Any]]",
        BaseRouter.std_error_responses(),
    ),
    summary="Get derived metrics time series for a metric view",
    description=(
        "Return a derived metrics time series for one or more companies using "
        "a predefined metric view (bundle). Views are opinionated metric sets "
        "such as 'core_fundamentals' that group margins, growth rates, cash "
        "flows, leverage, and returns.\n\n"
        "This endpoint reuses the same time-series structure as "
        "`/v1/edgar/derived-metrics/time-series` but selects metrics via the "
        "bundle code."
    ),
)
async def get_metric_view_timeseries(
    request: Request,
    response: Response,
    controller: Annotated[EdgarController, Depends(get_edgar_controller)],
    bundle_code: Annotated[
        str,
        Path(
            description=(
                "Metric view (bundle) code, e.g. 'core_fundamentals'. "
                "Bundle codes are case-insensitive."
            ),
            examples=["core_fundamentals"],
        ),
    ],
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
                "Optional list of derived metric codes to include. When a "
                "bundle_code is provided, explicit metrics are not allowed."
            ),
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
    """Get a derived metrics time series for a predefined metric view."""
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
        "views.api.get_metric_view_timeseries.start",
        extra={
            "bundle_code": bundle_code,
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
            bundle_code=bundle_code,
        )

        result = presenter.present_derived_timeseries(
            dtos=dtos,
            ciks=normalized_ciks,
            statement_type=typed_statement_type,
            frequency=normalized_frequency,
            from_date=effective_from_date,
            to_date=effective_to_date,
            trace_id=trace_id,
            view=bundle_code,
        )
        body = _apply_present_result(response, result)

        logger.info(
            "views.api.get_metric_view_timeseries.success",
            extra={
                "bundle_code": bundle_code,
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

    except ValueError as exc:
        # Controller-level validation (unknown bundle, bundle+metrics, etc.).
        response.status_code = status.HTTP_400_BAD_REQUEST
        return _error_envelope(
            http_status=400,
            code="VALIDATION_ERROR",
            message=str(exc),
            trace_id=trace_id,
            details={"bundle_code": bundle_code},
        )

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
            "views.api.get_metric_view_timeseries.unhandled",
            extra={
                "bundle_code": bundle_code,
                "ciks": normalized_ciks,
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
