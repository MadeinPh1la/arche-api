# Copyright
# SPDX-License-Identifier: MIT
"""Router: ``/v1/quotes/historical``.

Synopsis:
    FastAPI router exposing historical OHLCV bars (end-of-day and intraday) with
    a stable OpenAPI contract, pagination, ETag (If-None-Match) support, and
    structured error envelopes.

Layer:
    adapters/routers

Design:
    * Parse/validate HTTP query and header parameters; normalize date bounds.
    * Delegate to the application controller (no business logic here).
    * If the client’s ``If-None-Match`` matches the server ETag, return 304 with no body.
    * On success, return :class:`PaginatedEnvelope` via the presenter (adds headers).
    * On failures, return :class:`ErrorEnvelope` via :class:`~starlette.responses.JSONResponse`.

OpenAPI:
    * Stable ``operation_id="list_historical_quotes_v1"`` for clients/snapshots.
    * Success ``response_model`` is :class:`PaginatedEnvelope`.
    * Error responses (400/401/403/404/409/429/500/503) declared with :class:`ErrorEnvelope`.
"""

from __future__ import annotations

from datetime import UTC, date, datetime, time
from typing import Annotated

from fastapi import APIRouter, Header, Query, Response, status
from starlette.responses import JSONResponse

from stacklion_api.adapters.controllers.historical_quotes_controller import (
    HistoricalQuotesController,
)
from stacklion_api.adapters.presenters.market_data_presenter import MarketDataPresenter
from stacklion_api.adapters.routers.base_router import BaseRouter
from stacklion_api.adapters.schemas.http.envelopes import (
    ErrorEnvelope,
    PaginatedEnvelope,
)
from stacklion_api.adapters.schemas.http.quotes import HistoricalBarHTTP
from stacklion_api.application.schemas.dto.quotes import HistoricalBarDTO
from stacklion_api.domain.entities.historical_bar import BarInterval
from stacklion_api.domain.exceptions.market_data import (
    MarketDataBadRequest,
    MarketDataQuotaExceeded,
    MarketDataRateLimited,
    MarketDataUnavailable,
    MarketDataValidationError,
)
from stacklion_api.infrastructure.observability.metrics_market_data import (
    inc_market_data_error,
)

# ---------------------------------------------------------------------------
# Typed request parameters (validated, stable for OpenAPI)
# ---------------------------------------------------------------------------

TickersParam = Annotated[
    list[str],
    Query(
        min_length=1,
        max_length=50,
        description="One or more ticker symbols (comma-separated), e.g., AAPL, MSFT.",
    ),
]

FromDateParam = Annotated[
    date,
    Query(
        alias="from_",
        description="Start date (YYYY-MM-DD), inclusive; normalized to 00:00:00Z.",
    ),
]

ToDateParam = Annotated[
    date,
    Query(
        description="End date (YYYY-MM-DD), inclusive; normalized to 23:59:59.999999Z.",
    ),
]

IntervalParam = Annotated[
    str,
    Query(
        pattern=r"^(1d|1m|5m|15m|30m|1h)$",
        description="Bar interval (one of: 1m, 5m, 15m, 30m, 1h, 1d).",
    ),
]

PageParam = Annotated[int, Query(ge=1, description="1-based page number.")]
PageSizeParam = Annotated[int, Query(ge=1, le=1000, description="Items per page (≤ 1000).")]

IfNoneMatchHeader = Annotated[
    str | None,
    Header(
        alias="If-None-Match",
        description="ETag from a previous response to enable conditional GET.",
        convert_underscores=False,
    ),
]


class HistoricalQuotesRouter(BaseRouter):
    """HTTP adapter for historical OHLCV retrieval.

    This router is intentionally thin: it parses/validates input, delegates to
    the controller, and renders the HTTP response via the presenter.
    """

    def __init__(
        self,
        *,
        controller: HistoricalQuotesController,
        presenter: MarketDataPresenter,
    ) -> None:
        """Initialize the router.

        Args:
            controller: Application orchestration component for historical quotes.
            presenter: Presenter used to construct HTTP-layer envelopes and headers.
        """
        super().__init__(version="v1", resource="quotes", tags=["Market Data"])
        self._router = APIRouter(prefix="/v1/quotes", tags=["Market Data"])
        self._controller = controller
        # Type concretely so mypy sees present_list(...)
        self._presenter: MarketDataPresenter = presenter
        self._register()

    @property
    def router(self) -> APIRouter:
        """Expose the underlying :class:`APIRouter` for inclusion in FastAPI."""
        return self._router

    # -----------------------------------------------------------------------
    # Route registration
    # -----------------------------------------------------------------------

    def _register(self) -> None:
        """Register the ``/v1/quotes/historical`` endpoint with metadata."""

        @self._router.get(
            "/historical",
            name="List Historical Quotes",
            operation_id="list_historical_quotes_v1",
            response_model=PaginatedEnvelope,
            responses={
                status.HTTP_304_NOT_MODIFIED: {"description": "Not Modified (ETag matched)."},
                status.HTTP_400_BAD_REQUEST: {
                    "model": ErrorEnvelope,
                    "description": "Validation or parameter error.",
                },
                status.HTTP_401_UNAUTHORIZED: {
                    "model": ErrorEnvelope,
                    "description": "Unauthorized (missing/invalid auth)",
                },
                status.HTTP_403_FORBIDDEN: {
                    "model": ErrorEnvelope,
                    "description": "Forbidden (insufficient permissions).",
                },
                status.HTTP_404_NOT_FOUND: {"model": ErrorEnvelope, "description": "Not Found."},
                status.HTTP_409_CONFLICT: {"model": ErrorEnvelope, "description": "Conflict."},
                status.HTTP_429_TOO_MANY_REQUESTS: {
                    "model": ErrorEnvelope,
                    "description": "Rate limited / quota exceeded.",
                },
                status.HTTP_500_INTERNAL_SERVER_ERROR: {
                    "model": ErrorEnvelope,
                    "description": "Server error.",
                },
                status.HTTP_503_SERVICE_UNAVAILABLE: {
                    "model": ErrorEnvelope,
                    "description": "Upstream unavailable.",
                },
            },
            summary="Historical quotes",
            description=(
                "Return historical OHLCV bars (End-of-Day or intraday) for one or more tickers over a time range. "
                "Supports pagination and conditional requests via the `If-None-Match` header (ETag)."
            ),
        )
        async def list_historical_quotes(  # noqa: D401
            response: Response,
            *,
            tickers: TickersParam,
            from_: FromDateParam,
            to: ToDateParam,
            interval: IntervalParam,
            page: PageParam = 1,
            page_size: PageSizeParam = 50,
            if_none_match: IfNoneMatchHeader = None,
        ) -> PaginatedEnvelope[HistoricalBarHTTP] | Response:
            """Parse input, delegate to the controller, and render the response.

            Args are validated by FastAPI. See function signature for details.

            Returns:
                * :class:`PaginatedEnvelope[HistoricalBarHTTP]` with headers on success.
                * Bare 304 :class:`~fastapi.Response` (no body) when ETag matches.
                * :class:`~starlette.responses.JSONResponse` with :class:`ErrorEnvelope` on error.
            """
            start_at = _to_utc_start(from_)
            end_at = _to_utc_end(to)

            try:
                items, total, etag = await self._invoke(
                    tickers=list(tickers),
                    start=start_at,
                    end=end_at,
                    interval=interval,
                    page=int(page),
                    page_size=int(page_size),
                    if_none_match=if_none_match,
                )

                # Conditional GET: emit 304 with ETag (and echoed request-id headers).
                if etag and if_none_match and etag == if_none_match:
                    resp = Response(status_code=status.HTTP_304_NOT_MODIFIED)
                    self._presenter.apply_headers(resp, response)
                    resp.headers["ETag"] = etag
                    return resp

                # Success envelope with pagination headers and optional ETag.
                return self._presenter.present_list(
                    response=response,
                    items=items,
                    total=total,
                    page=page,
                    page_size=page_size,
                    etag=etag,
                )

            except MarketDataBadRequest as exc:
                return self._error_json(response, status.HTTP_400_BAD_REQUEST, "BAD_REQUEST", exc)
            except MarketDataValidationError as exc:
                return self._error_json(
                    response, status.HTTP_400_BAD_REQUEST, "VALIDATION_ERROR", exc
                )
            except (MarketDataRateLimited, MarketDataQuotaExceeded) as exc:
                # Record labeled error for metrics test.
                inc_market_data_error("rate_limited", "/v1/quotes/historical")
                return self._error_json(
                    response, status.HTTP_429_TOO_MANY_REQUESTS, "RATE_LIMITED", exc
                )
            except MarketDataUnavailable as exc:
                return self._error_json(
                    response, status.HTTP_503_SERVICE_UNAVAILABLE, "UPSTREAM_UNAVAILABLE", exc
                )
            except Exception as exc:  # noqa: BLE001
                return self._error_json(
                    response, status.HTTP_500_INTERNAL_SERVER_ERROR, "INTERNAL_ERROR", exc
                )

    # -----------------------------------------------------------------------
    # Internal helpers
    # -----------------------------------------------------------------------

    async def _invoke(
        self,
        *,
        tickers: list[str],
        start: datetime,
        end: datetime,
        interval: str,
        page: int,
        page_size: int,
        if_none_match: str | None,
    ) -> tuple[list[HistoricalBarDTO], int, str | None]:
        """Invoke the controller with normalized inputs and return domain DTOs.

        Returns:
            tuple[list[HistoricalBarDTO], int, str | None]: ``(items, total, etag)``.
        """
        upper = [t.upper() for t in tickers]
        return await self._controller.list(
            tickers=upper,
            from_=start,
            to=end,
            interval=BarInterval(interval),
            page=page,
            page_size=page_size,
            if_none_match=if_none_match,
        )

    def _error_json(
        self,
        response: Response,
        http_status: int,
        code: str,
        err: Exception,
    ) -> JSONResponse:
        """Return a JSON error with an :class:`ErrorEnvelope`."""
        result = self._presenter.present_error(
            code=code,
            http_status=http_status,
            message=str(err),
            trace_id=response.headers.get("X-Request-ID"),
        )
        # Apply headers (e.g., X-Request-ID; presenter may also set ETag if provided).
        self._presenter.apply_headers(result, response)
        return JSONResponse(
            status_code=int(http_status),
            content=result.body.model_dump_http(),
            headers=dict(result.headers),
        )


# ---------------------------------------------------------------------------
# UTC normalization helpers
# ---------------------------------------------------------------------------


def _to_utc_start(d: date | datetime) -> datetime:
    """Normalize a date/datetime to the start of day in UTC."""
    if isinstance(d, date) and not isinstance(d, datetime):
        return datetime.combine(d, time.min, tzinfo=UTC)
    if isinstance(d, datetime):
        return d if d.tzinfo else d.replace(tzinfo=UTC)
    return datetime.combine(date.today(), time.min, tzinfo=UTC)


def _to_utc_end(d: date | datetime) -> datetime:
    """Normalize a date/datetime to the end of day in UTC."""
    if isinstance(d, date) and not isinstance(d, datetime):
        return datetime.combine(d, time.max, tzinfo=UTC)
    if isinstance(d, datetime):
        return d if d.tzinfo else d.replace(tzinfo=UTC)
    return datetime.combine(date.today(), time.max, tzinfo=UTC)
