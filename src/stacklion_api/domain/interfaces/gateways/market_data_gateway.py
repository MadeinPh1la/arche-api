# Copyright (c) Stacklion.
# SPDX-License-Identifier: MIT
"""Market Data Gateway Protocol.

Synopsis:
    Domain-level Protocol (PEP 544) that abstracts external market data
    providers. Concrete implementations (e.g., Marketstack) live in the
    infrastructure layer and must satisfy this contract.

Design:
    * Keeps the domain/application layers independent of vendor SDKs/HTTP.
    * Covers both:
        - Latest quotes (A5)
        - Historical OHLCV bars with pagination (A6)
    * Avoids importing HTTP or infra types; uses domain/app DTOs only.

Layer:
    domain/interfaces/gateways
"""

from __future__ import annotations

from collections.abc import Sequence
from typing import Protocol

from stacklion_api.application.schemas.dto.quotes import HistoricalBarDTO, HistoricalQueryDTO
from stacklion_api.domain.entities.quote import Quote


class MarketDataGatewayProtocol(Protocol):
    """Abstraction over external market data providers.

    Implementations are responsible for:
      * Translating request parameters to provider calls.
      * Applying provider-specific resilience (timeouts/retries).
      * Mapping provider payloads to domain/app DTOs.
      * Raising domain exceptions (no HTTP types) on failures.

    Notes:
        Do not leak vendor or transport concerns (httpx responses, status codes)
        through this interface. Instead, translate to domain exceptions such as:
        `MarketDataUnavailable`, `MarketDataBadRequest`, `MarketDataRateLimited`,
        `MarketDataQuotaExceeded`, `MarketDataValidationError`, `SymbolNotFound`.
    """

    async def get_latest_quotes(self, tickers: Sequence[str]) -> list[Quote]:
        """Return the latest quote for each requested ticker.

        Args:
            tickers: Sequence of ticker symbols (uppercase).

        Returns:
            list[Quote]: Latest quotes matching the requested tickers. The list
            order is unspecified and may differ from the input order.

        Raises:
            MarketDataUnavailable: Provider unreachable or 5xx conditions.
            MarketDataValidationError: Provider payload invalid/unexpected.
            SymbolNotFound: No quotes for any requested symbols.
            MarketDataRateLimited: Upstream rate limits were exceeded.
            MarketDataQuotaExceeded: Account plan quota exhausted.
            MarketDataBadRequest: Invalid parameters sent upstream.
        """
        ...

    async def get_historical_bars(
        self, q: HistoricalQueryDTO
    ) -> tuple[list[HistoricalBarDTO], int]:
        """Return historical OHLCV bars (EOD or intraday), with pagination.

        Args:
            q: Historical query parameters (tickers, date/time range, interval,
               page, page_size).

        Returns:
            Tuple[List[HistoricalBarDTO], int]: A pair of (items, total) where
            `items` is the current page of bars and `total` is the total number
            of bars available upstream for the query.

        Raises:
            MarketDataUnavailable: Provider unreachable or 5xx conditions.
            MarketDataValidationError: Provider payload invalid/unexpected.
            SymbolNotFound: No data for the requested symbols.
            MarketDataRateLimited: Upstream rate limits were exceeded.
            MarketDataQuotaExceeded: Account plan quota exhausted.
            MarketDataBadRequest: Invalid parameters sent upstream.
        """
        ...
