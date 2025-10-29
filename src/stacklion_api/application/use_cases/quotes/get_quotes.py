# Copyright (c) Stacklion.
# SPDX-License-Identifier: MIT
"""
Use Case: Get Latest Quotes

Purpose:
    Orchestrate retrieval of latest quotes via market data gateway and
    return DTOs for presentation.

Layer: application/use_cases
"""
from __future__ import annotations

from collections.abc import Sequence
from decimal import Decimal

from stacklion_api.application.schemas.dto.quotes import QuoteDTO, QuotesBatchDTO
from stacklion_api.domain.entities.quote import Quote
from stacklion_api.domain.interfaces.gateways.market_data_gateway import MarketDataGatewayProtocol


class GetQuotes:
    """Use case to fetch latest quotes.

    Args:
        gateway: Market data gateway implementation.

    Returns:
        QuotesBatchDTO: Batch of quotes mapped from domain entities.

    Raises:
        MarketDataUnavailable: If provider is down.
        MarketDataValidationError: If provider payload is invalid.
    """

    def __init__(self, gateway: MarketDataGatewayProtocol) -> None:
        self._gateway = gateway

    async def execute(self, tickers: Sequence[str]) -> QuotesBatchDTO:
        """Fetch latest quotes.

        Args:
            tickers: Sequence of ticker symbols (upper-case).

        Returns:
            QuotesBatchDTO: Quotes in deterministic order of input.
        """
        quotes: list[Quote] = await self._gateway.get_latest_quotes(tickers)
        items = [
            QuoteDTO(
                ticker=q.ticker,
                price=Decimal(str(q.price)),
                currency=q.currency,
                as_of=q.as_of,
                volume=q.volume,
            )
            for q in quotes
        ]
        return QuotesBatchDTO(items=items)
