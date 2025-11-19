# Copyright (c) Stacklion.
# SPDX-License-Identifier: MIT
"""
Quotes Router.

Summary:
    Public endpoint returning latest quotes for up to 50 tickers.

Layer:
    adapters/routers

Versioning:
    This router exposes **v2** only under `/v2/quotes`.
"""
from __future__ import annotations

import hashlib
from typing import Annotated, Any, cast

from fastapi import Depends, HTTPException, Query, Request, Response, status
from pydantic import BaseModel, ConfigDict, Field

from stacklion_api.adapters.presenters.quotes_presenter import QuotesPresenter
from stacklion_api.adapters.routers.base_router import BaseRouter
from stacklion_api.adapters.schemas.http.envelopes import (
    ErrorEnvelope,
    ErrorObject,
    SuccessEnvelope,
)
from stacklion_api.adapters.schemas.http.quotes import QuotesBatch
from stacklion_api.application.use_cases.quotes.get_quotes import GetQuotes
from stacklion_api.dependencies.market_data import get_quotes_uc
from stacklion_api.domain.exceptions.market_data import (
    MarketDataUnavailable,
    MarketDataValidationError,
    SymbolNotFound,
)

# v2 only
router = BaseRouter(version="v2", resource="quotes", tags=["Market Data"])
presenter = QuotesPresenter()


class QuotesQuery(BaseModel):
    """Query parameters for `/v2/quotes`."""

    model_config = ConfigDict(extra="forbid")
    tickers: list[str] = Field(description="CSV list of tickers (1..50, UPPERCASE)")


def _parse_tickers(tickers_csv: str) -> list[str]:
    vals = [x.strip().upper() for x in tickers_csv.split(",") if x.strip()]
    if not (1 <= len(vals) <= 50) or any(len(v) > 12 for v in vals):
        raise HTTPException(status_code=400, detail="1..50 tickers required (<=12 chars each)")
    return vals


def _deterministic_etag(seed: str) -> str:
    """Return a strong ETag derived from a deterministic seed."""
    return f'"{hashlib.sha256(seed.encode("utf-8")).hexdigest()}"'


@router.get(
    "",
    response_model=SuccessEnvelope[QuotesBatch],
    status_code=status.HTTP_200_OK,
    responses=cast("dict[int | str, dict[str, Any]]", BaseRouter.std_error_responses()),
    summary="Get latest quotes for tickers",
)
async def get_quotes(
    request: Request,
    response: Response,
    tickers: Annotated[str, Query(examples=["AAPL,MSFT"])],
    uc: Annotated[GetQuotes, Depends(get_quotes_uc)],
) -> SuccessEnvelope[QuotesBatch] | ErrorEnvelope | Response:
    """Return the latest quotes for provided tickers.

    Returns:
        SuccessEnvelope on 200, ErrorEnvelope on error statuses,
        or a bare 304 Response when ETag matches.
    """
    trace_id = response.headers.get("X-Request-ID")

    try:
        q = QuotesQuery(tickers=_parse_tickers(tickers))

        # Conditional GET pre-check using a deterministic seed
        seed = "quotes:" + ",".join(q.tickers)
        etag = _deterministic_etag(seed)
        if_none_match = request.headers.get("If-None-Match")
        if if_none_match and if_none_match == etag:
            # 304: no body, but keep caching headers
            return Response(
                status_code=status.HTTP_304_NOT_MODIFIED,
                headers={"ETag": etag, "Cache-Control": "public, max-age=5"},
            )

        dto = await uc.execute(q.tickers)
        result = presenter.present_success(
            dto,
            trace_id=trace_id,
            enable_caching=True,
            cache_ttl_s=5,
            etag_seed=seed,
        )

        # Apply headers directly (ETag, X-Request-ID, Cache-Control, etc.)
        response.headers.update(dict(result.headers))

        # For this endpoint, presenter always returns a body on success.
        body = result.body
        if body is None:  # pragma: no cover - defensive guard
            raise RuntimeError("QuotesPresenter returned no body for a successful response")

        return body

    except SymbolNotFound as exc:
        response.status_code = status.HTTP_404_NOT_FOUND
        error = ErrorObject(
            code="SYMBOL_NOT_FOUND",
            http_status=404,
            message=str(exc),
            details={},
            trace_id=trace_id,
        )
        return ErrorEnvelope(error=error)

    except MarketDataValidationError as exc:
        response.status_code = status.HTTP_500_INTERNAL_SERVER_ERROR
        error = ErrorObject(
            code="UPSTREAM_SCHEMA_ERROR",
            http_status=500,
            message=str(exc),
            details={},
            trace_id=trace_id,
        )
        return ErrorEnvelope(error=error)

    except MarketDataUnavailable as exc:
        response.status_code = status.HTTP_503_SERVICE_UNAVAILABLE
        error = ErrorObject(
            code="MARKET_DATA_UNAVAILABLE",
            http_status=503,
            message=str(exc),
            details={},
            trace_id=trace_id,
        )
        return ErrorEnvelope(error=error)
