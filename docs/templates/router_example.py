# docs/templates/router_example.py
"""Example FastAPI router.

Purpose:
    Demonstrate the canonical pattern for HTTP endpoints using presenters + DTOs.

Layer:
    adapters

Notes:
    - Uses Contract Registry envelopes only.
    - Delegates business logic to use cases; no DB/ORM/domain in signatures.
"""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, Query

from stacklion_api.adapters.presenters.quotes_presenter import QuotesPresenter
from stacklion_api.adapters.schemas.http.envelopes import PaginatedEnvelope
from stacklion_api.adapters.schemas.http.quotes import HistoricalQuoteResponse
from stacklion_api.adapters.uow import UnitOfWork
from stacklion_api.application.use_cases.quotes.get_historical_quotes import (
    GetHistoricalQuotesUseCase,
)
from stacklion_api.dependencies.market_data import get_uow

router = APIRouter(
    prefix="/v1/market-data",
    tags=["Market Data"],
)


@router.get(
    "/historical-quotes",
    summary="Get historical quotes",
    description="Return historical OHLCV bars for the given ticker.",
    response_model=PaginatedEnvelope[HistoricalQuoteResponse],
)
async def get_historical_quotes(
    ticker: Annotated[str, Query(min_length=1, max_length=16)],
    uow: Annotated[UnitOfWork, Depends(get_uow)],
    page: Annotated[int, Query(ge=1)] = 1,
    page_size: Annotated[int, Query(ge=1, le=200)] = 50,
) -> PaginatedEnvelope[HistoricalQuoteResponse]:
    """Canonical HTTP endpoint for historical quotes.

    Args:
        ticker: Canonical ticker symbol (e.g., 'AAPL').
        page: 1-based page index.
        page_size: Number of items per page.
        uow: Unit-of-work resolved from DI.

    Returns:
        A paginated envelope of historical quotes.
    """
    use_case = GetHistoricalQuotesUseCase(uow=uow)
    presenter = QuotesPresenter()
    dto_page = await use_case.execute(
        ticker=ticker,
        page=page,
        page_size=page_size,
    )
    return presenter.present_historical_quotes_page(dto_page)
