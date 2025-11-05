# Copyright (c) Stacklion.
# SPDX-License-Identifier: MIT
"""
Quotes Router.

Summary:
    Public endpoint returning latest quotes for up to 50 tickers.

Layer:
    adapters/routers
"""
from __future__ import annotations

import hashlib
from typing import Annotated, Any, cast

from fastapi import Depends, HTTPException, Query, Request, Response, status
from pydantic import BaseModel, ConfigDict, Field

from stacklion_api.adapters.presenters.quotes_presenter import QuotesPresenter
from stacklion_api.adapters.routers.base_router import BaseRouter
from stacklion_api.adapters.schemas.http.base import BaseHTTPSchema
from stacklion_api.adapters.schemas.http.envelopes import SuccessEnvelope
from stacklion_api.adapters.schemas.http.quotes import QuotesBatch
from stacklion_api.application.use_cases.quotes.get_quotes import GetQuotes
from stacklion_api.dependencies.market_data import get_quotes_uc
from stacklion_api.domain.exceptions.market_data import (
    MarketDataUnavailable,
    MarketDataValidationError,
    SymbolNotFound,
)

router = BaseRouter(version="v1", resource="quotes", tags=["Market Data"])
presenter = QuotesPresenter()


class QuotesQuery(BaseModel):
    """Query parameters for `/v1/quotes`."""

    model_config = ConfigDict(extra="forbid")
    tickers: list[str] = Field(description="CSV list of tickers (1..50, UPPERCASE)")


def _parse_tickers(tickers_csv: str) -> list[str]:
    vals = [x.strip().upper() for x in tickers_csv.split(",") if x.strip()]
    if not (1 <= len(vals) <= 50) or any(len(v) > 12 for v in vals):
        raise HTTPException(status_code=400, detail="1..50 tickers required (<=12 chars each)")
    return vals


def _deterministic_etag(seed: str) -> str:
    """Return a strong ETag derived from a deterministic seed."""
    return f"\"{hashlib.sha256(seed.encode('utf-8')).hexdigest()}\""


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
) -> BaseHTTPSchema | dict[str, Any] | Response:
    """Return the latest quotes for provided tickers.

    Returns:
        SuccessEnvelope on 200, or a bare 304 Response when ETag matches.
    """
    try:
        q = QuotesQuery(tickers=_parse_tickers(tickers))

        # Conditional GET pre-check
        seed = "quotes:" + ",".join(q.tickers)
        etag = _deterministic_etag(seed)
        if_none_match = request.headers.get("If-None-Match")
        if if_none_match and if_none_match == etag:
            return Response(
                status_code=status.HTTP_304_NOT_MODIFIED,
                headers={"ETag": etag, "Cache-Control": "public, max-age=5"},
            )

        dto = await uc.execute(q.tickers)
        result = presenter.present_success(
            dto,
            trace_id=response.headers.get("X-Request-ID"),
            enable_caching=True,
            cache_ttl_s=5,
            etag_seed=seed,
        )

        # Apply headers directly to avoid mypy Protocol friction on Response.headers
        response.headers.update(dict(result.headers))
        return router.send_success(None, result)

    except SymbolNotFound as e:
        response.status_code = status.HTTP_404_NOT_FOUND
        return {
            "error": {
                "code": "SYMBOL_NOT_FOUND",
                "http_status": 404,
                "message": str(e),
                "details": {},
                "trace_id": response.headers.get("X-Request-ID"),
            }
        }
    except MarketDataValidationError as e:
        response.status_code = status.HTTP_500_INTERNAL_SERVER_ERROR
        return {
            "error": {
                "code": "UPSTREAM_SCHEMA_ERROR",
                "http_status": 500,
                "message": str(e),
                "details": {},
                "trace_id": response.headers.get("X-Request-ID"),
            }
        }
    except MarketDataUnavailable as e:
        response.status_code = status.HTTP_503_SERVICE_UNAVAILABLE
        return {
            "error": {
                "code": "MARKET_DATA_UNAVAILABLE",
                "http_status": 503,
                "message": str(e),
                "details": {},
                "trace_id": response.headers.get("X-Request-ID"),
            }
        }
