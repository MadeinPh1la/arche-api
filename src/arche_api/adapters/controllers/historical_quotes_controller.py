# Copyright (c) Arche.
# SPDX-License-Identifier: MIT
"""Controller: Historical Quotes.

Synopsis:
    Thin orchestration layer that turns HTTP-friendly parameters into a
    :class:`HistoricalQueryDTO` and forwards the call to the use-case.

Layer:
    adapters/controllers
"""
from __future__ import annotations

from collections.abc import Sequence
from datetime import datetime

from arche_api.application.schemas.dto.quotes import HistoricalBarDTO, HistoricalQueryDTO
from arche_api.application.use_cases.quotes.get_historical_quotes import (
    GetHistoricalQuotesUseCase,
)
from arche_api.domain.entities.historical_bar import BarInterval


class HistoricalQuotesController:
    """Controller delegating to :class:`GetHistoricalQuotesUseCase`."""

    def __init__(self, uc: GetHistoricalQuotesUseCase) -> None:
        """Initialize the controller.

        Args:
            uc: Use-case instance to execute queries against.
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
        if_none_match: str | None,
    ) -> tuple[list[HistoricalBarDTO], int, str]:
        """List historical OHLCV bars.

        Args:
            tickers: Symbols to query (case-insensitive).
            from_: Inclusive start bound (UTC).
            to: Inclusive end bound (UTC).
            interval: Aggregation interval.
            page: 1-based page number.
            page_size: Items per page.
            if_none_match: Optional conditional ETag.

        Returns:
            tuple[list[HistoricalBarDTO], int, str]: Items, total, and ETag.
        """
        q = HistoricalQueryDTO(
            tickers=list(tickers),
            from_=from_,
            to=to,
            interval=interval,
            page=page,
            page_size=page_size,
        )
        return await self._uc.execute(q, if_none_match=if_none_match)
