# src/arche_api/adapters/routers/historical_quotes_router.py
# Copyright (c) Arche.
# SPDX-License-Identifier: MIT
"""Historical Quotes Router (A6, v2).

Synopsis:
    HTTP surface for retrieving historical OHLCV bars. Validates query parameters,
    invokes the `GetHistoricalQuotesUseCase`, and returns a canonical paginated
    envelope. Supports conditional requests (304) via `If-None-Match`.

Design:
    * Presentation-only: builds DTOs, delegates to UC, shapes response.
    * Returns PaginatedEnvelope directly on 200 (governance rule for list endpoints).
    * Emits standard error envelopes on 4xx/5xx without tripping FastAPI's
      response_model validation (errors are returned as JSONResponse).
    * ETags are supplied by the use case; 304 is emitted when they match.
    * Observability: metrics owned by UC / gateway; router stays thin.

Layer:
    adapters/routers

Versioning:
    This router exposes **v2** under `/v2/quotes/historical`.
"""

from __future__ import annotations

from datetime import UTC, date, datetime
from typing import Annotated, Any, Literal, cast

from fastapi import Depends, HTTPException, Query, Request, Response, status
from fastapi.responses import JSONResponse

from arche_api.adapters.routers.base_router import BaseRouter
from arche_api.adapters.schemas.http.envelopes import PaginatedEnvelope
from arche_api.application.schemas.dto.quotes import HistoricalQueryDTO
from arche_api.application.use_cases.quotes.get_historical_quotes import (
    GetHistoricalQuotesUseCase,
)
from arche_api.dependencies.market_data import get_historical_quotes_use_case
from arche_api.domain.exceptions.market_data import (
    MarketDataBadRequest,
    MarketDataQuotaExceeded,
    MarketDataRateLimited,
    MarketDataUnavailable,
    MarketDataValidationError,
)

# v2
router = BaseRouter(version="v2", resource="quotes", tags=["Market Data"])


# --------------------------------------------------------------------------- #
# Parsers                                                                     #
# --------------------------------------------------------------------------- #
def _parse_interval(val: str) -> str:
    """Parse interval from query string to a canonical string value.

    Args:
        val: Query value (e.g., "1d", "1m").

    Returns:
        Canonical interval value ("1d" or "1m").

    Raises:
        HTTPException: On unsupported interval string.
    """
    up = val.strip().lower()
    if up in {"1d", "i1d", "barinterval.i1d"}:
        return "1d"
    if up in {"1m", "i1m", "barinterval.i1m"}:
        return "1m"
    raise HTTPException(status_code=400, detail="Unsupported interval; use 1d or 1m")


def _parse_date(val: str, *, name: str) -> datetime:
    """Parse an ISO date into UTC midnight.

    Args:
        val: Date string (YYYY-MM-DD).
        name: Parameter name (for error messages).

    Returns:
        Aware UTC midnight for the day.

    Raises:
        HTTPException: On invalid format.
    """
    try:
        d = date.fromisoformat(val)
        return datetime(d.year, d.month, d.day, tzinfo=UTC)
    except Exception as e:  # pragma: no cover - defensive
        raise HTTPException(status_code=400, detail=f"Invalid {name} date") from e


def _parse_pagination(page: int, page_size: int) -> tuple[int, int]:
    """Validate pagination.

    Args:
        page: 1-based page.
        page_size: Items per page.

    Returns:
        Tuple of validated (page, page_size).

    Raises:
        HTTPException: On invalid bounds.
    """
    if page < 1:
        raise HTTPException(status_code=400, detail="page must be >= 1")
    if not (1 <= page_size <= 500):
        raise HTTPException(status_code=400, detail="page_size must be 1..500")
    return page, page_size


def _dump_item(obj: object) -> dict[str, Any]:
    """Best-effort DTO → dict without closures (avoids B023).

    Args:
        obj: DTO / mapping-like / object with `model_dump` / `__dict__`.

    Returns:
        Dict representation.
    """
    if isinstance(obj, dict):
        return obj
    if hasattr(obj, "model_dump"):
        # Pydantic v2 model: get a plain dict.
        return obj.model_dump()
    return dict(getattr(obj, "__dict__", {}))


# --------------------------------------------------------------------------- #
# Route                                                                       #
# --------------------------------------------------------------------------- #
@router.get(
    "/historical",
    # IMPORTANT: keep the generic PaginatedEnvelope here so OpenAPI uses the
    # canonical schema name, not a specialized PaginatedEnvelope_... variant.
    response_model=PaginatedEnvelope,
    status_code=status.HTTP_200_OK,
    responses=cast("dict[int | str, dict[str, Any]]", BaseRouter.std_error_responses()),
    summary="Get historical quotes (OHLCV bars)",
    description=(
        "Returns historical OHLCV bars for the requested tickers and time window. "
        "Supports daily (1d) and intraday (1m) intervals. Results are paginated and "
        "conditionally cacheable via ETag (weak)."
    ),
)
async def get_historical_quotes(
    request: Request,
    response: Response,
    uc: Annotated[GetHistoricalQuotesUseCase, Depends(get_historical_quotes_use_case)],
    tickers: Annotated[
        list[str], Query(min_length=1, max_length=50, description="List of tickers.")
    ],
    from_: Annotated[str, Query(description="Start date (YYYY-MM-DD).")],
    to: Annotated[str, Query(description="End date (YYYY-MM-DD).")],
    interval: Annotated[Literal["1d", "1m"], Query(description="Bar interval (1d or 1m).")],
    page: Annotated[int, Query(ge=1, description="1-based page.")] = 1,
    page_size: Annotated[int, Query(ge=1, le=500, description="Items per page.")] = 50,
) -> dict[str, Any] | JSONResponse:
    """Return historical OHLCV bars for tickers within the requested window.

    Behavior:
        * Builds a `HistoricalQueryDTO` from query params.
        * Delegates to the use case (`uc.execute`).
        * If `If-None-Match` equals the UC-supplied ETag, returns 304 with no body.
        * Otherwise returns a canonical paginated body (PaginatedEnvelope shape) on 200.

    Args:
        request: Incoming HTTP request.
        response: Outgoing HTTP response.
        uc: Historical quotes use case dependency.
        tickers: List of ticker symbols (1..50, non-empty).
        from_: Inclusive start date in YYYY-MM-DD format.
        to: Inclusive end date in YYYY-MM-DD format.
        interval: Requested bar interval (`1d` or `1m`).
        page: 1-based page number.
        page_size: Number of items per page (1..500).

    Returns:
        A PaginatedEnvelope-compatible dict on 200, or a bare 304/JSON error response.
    """
    # Basic param validation & normalization.
    if not (1 <= len(tickers) <= 50) or any(len(t.strip()) == 0 for t in tickers):
        return _error_json(
            status.HTTP_400_BAD_REQUEST,
            "VALIDATION_ERROR",
            "1..50 non-empty tickers required.",
            request,
        )

    tickers = [t.strip().upper() for t in tickers]
    try:
        iv = _parse_interval(interval)
        dt_from = _parse_date(from_, name="from")
        dt_to = _parse_date(to, name="to")
        page, page_size = _parse_pagination(page, page_size)
    except HTTPException as e:
        # Convert parser validation to standard error envelope (bypass response_model).
        return _error_json(e.status_code, "VALIDATION_ERROR", e.detail, request)

    q = HistoricalQueryDTO(
        tickers=tickers,
        from_=dt_from,
        to=dt_to,
        interval=iv,
        page=page,
        page_size=page_size,
    )

    if_none_match = request.headers.get("If-None-Match")

    try:
        # Use case returns (items, total, etag).
        items, total, etag = await uc.execute(q, if_none_match=if_none_match)

        # Conditional GET check against UC-supplied (or upstream) ETag.
        if if_none_match and etag and if_none_match == etag:
            # 304 - no body, but keep ETag/Cache-Control headers.
            return JSONResponse(
                status_code=status.HTTP_304_NOT_MODIFIED,
                content=None,
                headers={"ETag": etag, "Cache-Control": "public, max-age=60"},
            )

        # Success (200) path: return PaginatedEnvelope-compatible body.
        if etag:
            response.headers["ETag"] = etag
        response.headers.setdefault("Cache-Control", "public, max-age=60")

        return {
            "items": [_dump_item(i) for i in items],
            "total": total,
            "page": page,
            "page_size": page_size,
        }

    except MarketDataValidationError as e:
        return _error_json(status.HTTP_400_BAD_REQUEST, "VALIDATION_ERROR", str(e), request)
    except MarketDataRateLimited:
        return _error_json(
            status.HTTP_429_TOO_MANY_REQUESTS, "RATE_LIMITED", "Rate limit from upstream.", request
        )
    except MarketDataQuotaExceeded:
        return _error_json(
            status.HTTP_402_PAYMENT_REQUIRED,
            "PROVIDER_QUOTA_EXCEEDED",
            "Provider quota exceeded.",
            request,
        )
    except MarketDataBadRequest:
        return _error_json(
            status.HTTP_400_BAD_REQUEST,
            "UPSTREAM_SCHEMA_ERROR",
            "Upstream schema/shape error.",
            request,
        )
    except MarketDataUnavailable:
        return _error_json(
            status.HTTP_503_SERVICE_UNAVAILABLE,
            "MARKET_DATA_UNAVAILABLE",
            "Market data unavailable.",
            request,
        )


# --------------------------------------------------------------------------- #
# Error envelope helper                                                       #
# --------------------------------------------------------------------------- #
def _error_json(http_status: int, code: str, message: str, request: Request) -> JSONResponse:
    """Return a JSONResponse with the standard error envelope.

    This explicitly bypasses the route's `response_model` to avoid FastAPI trying
    to validate an error body against the success envelope.

    Args:
        http_status: HTTP status code to set (e.g., 400).
        code: Stable, machine-readable error code.
        message: Human-readable message.
        request: Starlette request, used to propagate a trace identifier.

    Returns:
        JSONResponse with canonical error envelope.
    """
    trace_id = request.headers.get("X-Request-ID") or request.headers.get("X-Trace-ID")
    body = {
        "error": {
            "code": code,
            "http_status": http_status,
            "message": message,
            "details": {},
            "trace_id": trace_id,
        }
    }
    return JSONResponse(status_code=http_status, content=body)
