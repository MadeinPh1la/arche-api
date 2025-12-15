# Copyright (c) Arche.
# SPDX-License-Identifier: MIT
"""Quotes Controller.

Summary:
    Thin adapter coordinating the GetQuotes use-case.

Layer:
    adapters/controllers
"""
from __future__ import annotations

from collections.abc import Sequence

from arche_api.adapters.controllers.base import BaseController
from arche_api.application.schemas.dto.quotes import QuotesBatchDTO
from arche_api.application.use_cases.quotes.get_quotes import GetQuotes


class QuotesController(BaseController):
    """Controller orchestrating latest quotes retrieval."""

    def __init__(self, use_case: GetQuotes) -> None:
        """Initialize the controller.

        Args:
            use_case: Use-case that fetches latest quotes.
        """
        self._uc = use_case

    async def get_latest(self, tickers: Sequence[str]) -> QuotesBatchDTO:
        """Fetch the latest quotes for the given tickers.

        Args:
            tickers: Sequence of upper-case ticker symbols.

        Returns:
            QuotesBatchDTO: Batch of quotes.
        """
        return await self._uc.execute(tickers=tickers)
