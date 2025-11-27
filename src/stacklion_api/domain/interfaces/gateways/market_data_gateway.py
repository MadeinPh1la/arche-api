# src/stacklion_api/domain/interfaces/gateways/market_data_gateway.py
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
        - Latest quotes (A5).
        - Historical OHLCV bars with pagination (A6).
    * Avoids importing HTTP, infrastructure types, or application DTOs.
      Implementations may use application-level DTOs, but this protocol
      stays agnostic and relies on structural typing.

Layer:
    domain/interfaces/gateways
"""

from __future__ import annotations

from collections.abc import Sequence
from typing import Any, Protocol

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

        For historical data (A6), concrete implementations typically accept
        an application-level DTO (e.g. ``HistoricalQueryDTO``) and return
        DTO-like objects (e.g. ``HistoricalBarDTO``). This protocol does not
        depend on those types directly to preserve clean layering; it only
        requires that ``q`` exposes the expected attributes and that returned
        items are JSON-serializable.
    """

    async def get_latest_quotes(self, tickers: Sequence[str]) -> list[Quote]:
        """Return the latest quote for each requested ticker.

        Args:
            tickers: Sequence of ticker symbols (uppercase).

        Returns:
            Latest quotes matching the requested tickers. The list order is
            unspecified and may differ from the input order.

        Raises:
            MarketDataUnavailable: Provider unreachable or 5xx conditions.
            MarketDataValidationError: Provider payload invalid/unexpected.
            SymbolNotFound: No quotes for any requested symbols.
            MarketDataRateLimited: Upstream rate limits were exceeded.
            MarketDataQuotaExceeded: Account plan quota exhausted.
            MarketDataBadRequest: Invalid parameters sent upstream.
        """
        ...

    async def get_historical_bars(self, q: Any) -> tuple[list[Any], int]:
        """Return historical OHLCV bars (EOD or intraday), with pagination.

        Args:
            q:
                Historical query parameters (tickers, date/time range, interval,
                page, page_size). In practice this is typically an application-
                level DTO (e.g. ``HistoricalQueryDTO``), but any object with the
                required attributes is acceptable.

        Returns:
            A pair ``(items, total)`` where:

                * ``items`` is the current page of bars.
                * ``total`` is the total number of bars available upstream
                  for the query.

            Implementations commonly return a list of DTOs equivalent to
            ``HistoricalBarDTO``, but this protocol does not prescribe the
            concrete type beyond being JSON-serializable.

        Raises:
            MarketDataUnavailable: Provider unreachable or 5xx conditions.
            MarketDataValidationError: Provider payload invalid/unexpected.
            SymbolNotFound: No data for the requested symbols.
            MarketDataRateLimited: Upstream rate limits were exceeded.
            MarketDataQuotaExceeded: Account plan quota exhausted.
            MarketDataBadRequest: Invalid parameters sent upstream.
        """
        ...
