# Copyright (c) Stacklion.
# SPDX-License-Identifier: MIT
"""
Quotes Router (v2).

Summary:
    Public endpoint returning latest quotes for up to 50 tickers.

HTTP Contract:
    • Route:   GET /v2/quotes
    • Success: 200 → SuccessEnvelope[QuotesBatch]
    • Errors:  4xx/5xx → ErrorEnvelope (see BaseRouter.std_error_responses)
    • Caching: Strong ETag + short Cache-Control (5s) on success.
    • 304:     Returned when If-None-Match matches the deterministic seed-based ETag.

Layer:
    adapters/routers

Versioning:
    This router exposes v2 only under `/v2/quotes`.
"""

from __future__ import annotations

import hashlib
from typing import Annotated, Any, cast

from fastapi import Depends, HTTPException, Query, Request, Response, status

from stacklion_api.adapters.presenters.quotes_presenter import QuotesPresenter
from stacklion_api.adapters.routers.base_router import BaseRouter
from stacklion_api.adapters.schemas.http import (
    ErrorEnvelope,
    ErrorObject,
    QuotesBatch,
    SuccessEnvelope,
)
from stacklion_api.application.use_cases.quotes.get_quotes import GetQuotes
from stacklion_api.dependencies.market_data import get_quotes_uc
from stacklion_api.domain.exceptions.market_data import (
    MarketDataUnavailable,
    MarketDataValidationError,
    SymbolNotFound,
)

router = BaseRouter(version="v2", resource="quotes", tags=["Market Data"])
presenter = QuotesPresenter()


def _parse_tickers(tickers_csv: str) -> list[str]:
    """Parse and validate CSV tickers into [UPPER_CASE, ...]."""
    vals = [x.strip().upper() for x in tickers_csv.split(",") if x.strip()]
    if not (1 <= len(vals) <= 50) or any(len(v) > 12 for v in vals):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="1..50 tickers required (<=12 chars each)",
        )
    return vals


def _deterministic_etag(seed: str) -> str:
    """Return a strong, quoted ETag derived from a deterministic seed."""
    return f"\"{hashlib.sha256(seed.encode('utf-8')).hexdigest()}\""


def _error_envelope(
    *,
    http_status: int,
    code: str,
    message: str,
    trace_id: str | None,
) -> ErrorEnvelope:
    """Build a canonical ErrorEnvelope for this router."""
    return ErrorEnvelope(
        error=ErrorObject(
            code=code,
            http_status=http_status,
            message=message,
            details={},
            trace_id=trace_id,
        )
    )


@router.get(
    "",
    response_model=SuccessEnvelope[QuotesBatch],
    status_code=status.HTTP_200_OK,
    responses=cast("dict[int | str, dict[str, Any]]", BaseRouter.std_error_responses()),
    summary="Get latest quotes for tickers",
    description=(
        "Return the latest quotes for up to 50 ticker symbols. "
        "ETag-based conditional GET is supported with a short cache window."
    ),
)
async def get_quotes(
    request: Request,
    response: Response,
    tickers: Annotated[str, Query(examples=["AAPL,MSFT"], description="Comma-separated tickers.")],
    uc: Annotated[GetQuotes, Depends(get_quotes_uc)],
) -> SuccessEnvelope[QuotesBatch] | ErrorEnvelope | Response:
    """Return the latest quotes for the requested tickers.

    Success:
        200 SuccessEnvelope[QuotesBatch] with a strong ETag and Cache-Control.
        304 with no body when If-None-Match matches the deterministic seed-based ETag.

    Errors:
        404 SYMBOL_NOT_FOUND
        500 UPSTREAM_SCHEMA_ERROR
        503 MARKET_DATA_UNAVAILABLE
    """
    trace_id = response.headers.get("X-Request-ID")

    try:
        parsed_tickers = _parse_tickers(tickers)

        # Deterministic ETag seed by tickers (order-preserving).
        seed = "v2:quotes:" + ",".join(parsed_tickers)
        etag = _deterministic_etag(seed)
        if_none_match = request.headers.get("If-None-Match")

        # Conditional GET short-circuit.
        if if_none_match and if_none_match == etag:
            return Response(
                status_code=status.HTTP_304_NOT_MODIFIED,
                headers={"ETag": etag, "Cache-Control": "public, max-age=5"},
            )

        dto = await uc.execute(parsed_tickers)
        result = presenter.present_success(
            dto,
            trace_id=trace_id,
            enable_caching=True,
            cache_ttl_s=5,
            etag_seed=seed,
        )

        # Apply presenter headers and return canonical envelope.
        response.headers.update(dict(result.headers))
        return result.body

    except SymbolNotFound as exc:
        response.status_code = status.HTTP_404_NOT_FOUND
        return _error_envelope(
            http_status=status.HTTP_404_NOT_FOUND,
            code="SYMBOL_NOT_FOUND",
            message=str(exc),
            trace_id=trace_id,
        )

    except MarketDataValidationError as exc:
        response.status_code = status.HTTP_500_INTERNAL_SERVER_ERROR
        return _error_envelope(
            http_status=status.HTTP_500_INTERNAL_SERVER_ERROR,
            code="UPSTREAM_SCHEMA_ERROR",
            message=str(exc),
            trace_id=trace_id,
        )

    except MarketDataUnavailable as exc:
        response.status_code = status.HTTP_503_SERVICE_UNAVAILABLE
        return _error_envelope(
            http_status=status.HTTP_503_SERVICE_UNAVAILABLE,
            code="MARKET_DATA_UNAVAILABLE",
            message=str(exc),
            trace_id=trace_id,
        )
