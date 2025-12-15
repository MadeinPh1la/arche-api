# src/arche_api/adapters/routers/quotes_router.py
# Copyright (c) Arche.
# SPDX-License-Identifier: MIT
"""Quotes Router.

Summary:
    Public endpoint returning latest quotes for up to 50 tickers.

Layer:
    adapters/routers

Versioning:
    This router exposes **v2** under `/v2/quotes`.
"""

from __future__ import annotations

import hashlib
from typing import Annotated, Any, cast

from fastapi import Depends, HTTPException, Query, Request, Response, status
from pydantic import BaseModel, ConfigDict, Field

from arche_api.adapters.presenters.quotes_presenter import QuotesPresenter
from arche_api.adapters.routers.base_router import BaseRouter
from arche_api.adapters.schemas.http.envelopes import (
    ErrorEnvelope,
    ErrorObject,
    SuccessEnvelope,
)
from arche_api.adapters.schemas.http.quotes import QuotesBatch
from arche_api.application.use_cases.quotes.get_quotes import GetQuotes
from arche_api.dependencies.market_data import get_quotes_uc
from arche_api.domain.exceptions.market_data import (
    MarketDataBadRequest,
    MarketDataUnavailable,
    MarketDataValidationError,
    SymbolNotFound,
)

# v2
router = BaseRouter(version="v2", resource="quotes", tags=["Market Data"])
presenter = QuotesPresenter()


class QuotesQuery(BaseModel):
    """Query parameters for `/v2/quotes`.

    Attributes:
        tickers: List of ticker symbols (1..50, uppercase, <= 12 chars).
    """

    model_config = ConfigDict(extra="forbid")

    tickers: list[str] = Field(
        description="CSV list of tickers (1..50, UPPERCASE, <=12 chars).",
    )


def _parse_tickers(tickers_csv: str) -> list[str]:
    """Parse and validate the tickers CSV string.

    Args:
        tickers_csv: Comma-separated ticker symbols from the query string.

    Returns:
        Normalized list of uppercase ticker symbols.

    Raises:
        HTTPException: If bounds or individual symbol constraints are violated.
    """
    vals = [x.strip().upper() for x in tickers_csv.split(",") if x.strip()]
    if not (1 <= len(vals) <= 50) or any(len(v) > 12 for v in vals):
        raise HTTPException(status_code=400, detail="1..50 tickers required (<=12 chars each).")
    return vals


def _deterministic_etag(seed: str) -> str:
    """Return a strong ETag derived from a deterministic seed.

    Args:
        seed: Stable seed string (e.g., canonical tickers key).

    Returns:
        Strong ETag string suitable for use in `ETag` / `If-None-Match`.
    """
    return f'"{hashlib.sha256(seed.encode("utf-8")).hexdigest()}"'


@router.get(
    "",
    response_model=SuccessEnvelope[QuotesBatch] | ErrorEnvelope,
    status_code=status.HTTP_200_OK,
    responses=cast("dict[int | str, dict[str, Any]]", BaseRouter.std_error_responses()),
    summary="Get latest quotes for tickers.",
)
async def get_quotes(
    request: Request,
    response: Response,
    tickers: Annotated[str, Query(examples=["AAPL,MSFT"])],
    uc: Annotated[GetQuotes, Depends(get_quotes_uc)],
) -> SuccessEnvelope[QuotesBatch] | ErrorEnvelope | Response:
    """Return the latest quotes for provided tickers.

    Behavior:
        * Parses and validates the `tickers` CSV into a normalized list.
        * Uses a read-through cache (via the use case) for hot latest quotes.
        * Emits a weak ETag based on the canonical ticker set and respects
          conditional requests via `If-None-Match`.
        * Returns a canonical `SuccessEnvelope[QuotesBatch]` on success or an
          `ErrorEnvelope` on known domain/market-data failures.

    Args:
        request: Incoming HTTP request.
        response: Outgoing HTTP response.
        tickers: Comma-separated list of tickers.
        uc: Quotes use case dependency.

    Returns:
        SuccessEnvelope on 200, ErrorEnvelope on error statuses,
        or a bare 304 `Response` when the ETag matches.
    """
    trace_id = response.headers.get("X-Request-ID") or request.headers.get("X-Trace-ID")

    try:
        q = QuotesQuery(tickers=_parse_tickers(tickers))

        # Conditional GET pre-check using a deterministic seed.
        seed = "quotes:" + ",".join(q.tickers)
        etag = _deterministic_etag(seed)
        if_none_match = request.headers.get("If-None-Match")
        if if_none_match and if_none_match == etag:
            # 304: no body, but keep caching headers.
            return Response(
                status_code=status.HTTP_304_NOT_MODIFIED,
                headers={
                    "ETag": etag,
                    "Cache-Control": "public, max-age=5",
                },
            )

        dto = await uc.execute(q.tickers)
        result = presenter.present_success(
            dto,
            trace_id=trace_id,
            enable_caching=True,
            cache_ttl_s=5,
            etag_seed=seed,
        )

        # Apply headers directly (ETag, X-Request-ID, Cache-Control, etc.).
        response.headers.update(dict(result.headers))

        # For this endpoint, presenter always returns a body on success.
        body = result.body
        if body is None:  # pragma: no cover - defensive guard
            raise RuntimeError("QuotesPresenter returned no body for a successful response.")

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
        # This is treated as an upstream schema/shape issue here, not user error.
        response.status_code = status.HTTP_500_INTERNAL_SERVER_ERROR
        error = ErrorObject(
            code="UPSTREAM_SCHEMA_ERROR",
            http_status=response.status_code,
            message=str(exc),
            details={},
            trace_id=trace_id,
        )
        return ErrorEnvelope(error=error)

    except MarketDataBadRequest as exc:
        # Upstream rejected the request (e.g., invalid plan, credentials, or params).
        details = getattr(exc, "details", {}) or {}
        response.status_code = status.HTTP_502_BAD_GATEWAY
        error = ErrorObject(
            code="MARKET_DATA_BAD_REQUEST",
            http_status=response.status_code,
            message="Upstream market data provider rejected the request.",
            details=details,
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
