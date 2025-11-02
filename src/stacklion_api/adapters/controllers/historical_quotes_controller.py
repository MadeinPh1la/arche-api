# Copyright (c) Stacklion.
# SPDX-License-Identifier: MIT
"""
Controller: Historical Quotes.

Synopsis:
    Thin orchestration layer that adapts adapter-level inputs to the use-case
    DTOs and returns application-level results (items, total, etag). This
    controller is HTTP-agnostic and must not import web frameworks.

Layer:
    adapters/controllers
"""

from __future__ import annotations

import builtins
from collections.abc import Sequence
from datetime import datetime

from stacklion_api.adapters.controllers.base import BaseController
from stacklion_api.application.schemas.dto.quotes import HistoricalBarDTO, HistoricalQueryDTO
from stacklion_api.application.use_cases.quotes.get_historical_quotes import (
    GetHistoricalQuotesUseCase,
)
from stacklion_api.domain.entities.historical_bar import BarInterval


class HistoricalQuotesController(BaseController):
    """Controller orchestrating the historical quotes flow.

    Bridges adapter inputs into the application use-case for historical OHLCV
    retrieval, including pagination.
    """

    def __init__(self, uc: GetHistoricalQuotesUseCase) -> None:
        """Initialize the controller.

        Args:
            uc: Use-case instance that executes the historical query.
        """
        self._uc = uc

    async def list(
        self,
        *,
        tickers: Sequence[str],
        from_: datetime,
        to: datetime,
        interval: BarInterval,
        page: int,
        page_size: int,
        if_none_match: str | None = None,  # kept for router compatibility; ignored here
    ) -> tuple[builtins.list[HistoricalBarDTO], int, str]:
        """List historical OHLCV bars via the use-case.

        Args:
            tickers: One or more ticker symbols (case-insensitive).
            from_: Inclusive start datetime (UTC).
            to: Inclusive end datetime (UTC).
            interval: Bar interval enum (e.g., BarInterval.I1D, BarInterval.I1M).
            page: Page number (1-based).
            page_size: Page size.
            if_none_match: Optional ETag from client (handled at HTTP layer).

        Returns:
            Tuple[List[HistoricalBarDTO], int, str]: Items, total count, and ETag.
        """
        q = HistoricalQueryDTO(
            tickers=[t.upper() for t in tickers],
            from_=from_,
            to=to,
            interval=interval,
            page=page,
            page_size=page_size,
        )
        return await self._uc.execute(q)
