# src/arche_api/application/interfaces/market_data_gateway.py
# Copyright (c)
# SPDX-License-Identifier: MIT
"""Application-level Market Data Gateway interface.

Synopsis:
    Application-facing abstraction over external market data providers.

    This interface sits between:
        * Application use cases (A5 latest quotes, A6 historical bars,
          intraday ingest), and
        * Concrete adapter gateways (e.g. ``MarketstackGateway`` in
          ``adapters/gateways/marketstack_gateway.py``).

    It uses application DTOs for read paths and a small ingest record type
    for write paths, while the domain-level protocol
    ``arche_api.domain.interfaces.gateways.market_data_gateway
    .MarketDataGatewayProtocol`` stays vendor-agnostic and free of DTO
    dependencies.

Layer:
    application/interfaces
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from datetime import datetime
from typing import Any, Protocol

from arche_api.application.schemas.dto.quotes import (
    HistoricalBarDTO,
    HistoricalQueryDTO,
)
from arche_api.domain.entities.quote import Quote


@dataclass(frozen=True)
class IntradayBarRecord:
    """Provider-agnostic intraday bar record for ingest pipelines.

    Notes:
        * All numeric values are represented as strings to avoid precision loss
          when persisting and to keep the ingest pipeline independent of any
          particular Decimal / float policy.
        * ``ts`` is an ISO-8601 timestamp in UTC, typically normalized to the
          format ``YYYY-MM-DDTHH:MM:SSZ`` by the gateway.
    """

    symbol: str
    ts: str  # ISO-8601 UTC timestamp (e.g. "2025-11-25T15:30:00Z")
    open: str
    high: str
    low: str
    close: str
    volume: str


class MarketDataGateway(Protocol):
    """Application-level market data gateway.

    Responsibilities:
        * Serve A5 (latest quotes) using domain ``Quote`` entities.
        * Serve A6 (historical OHLCV) using application DTOs for stability.
        * Provide an ingest surface for intraday bars using
          :class:`IntradayBarRecord`.

    This interface is implemented by adapter gateways such as
    ``MarketstackGateway``. Use cases in ``application/use_cases/quotes`` and
    ingest flows in ``application/use_cases/external_apis/marketstack`` should
    depend on this interface, not on concrete gateways.
    """

    # ------------------------------------------------------------------ #
    # Read-side APIs (used by quotes / historical use cases)             #
    # ------------------------------------------------------------------ #
    async def get_latest_quotes(self, tickers: Sequence[str]) -> list[Quote]:
        """Return the latest quote for each requested ticker.

        Args:
            tickers:
                Sequence of ticker symbols (typically uppercase, but the
                gateway may normalize).

        Returns:
            A list of :class:`Quote` entities, in no particular order. Missing
            symbols may be omitted from the result.

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
        self,
        q: HistoricalQueryDTO,
    ) -> tuple[list[HistoricalBarDTO], int]:
        """Return historical OHLCV bars (EOD or intraday), with pagination.

        Args:
            q:
                Historical query parameters including tickers, UTC time window,
                interval, page, and page_size.

        Returns:
            A pair ``(items, total)`` where:

                * ``items`` is the current page of :class:`HistoricalBarDTO`
                  objects; and
                * ``total`` is the total number of bars available upstream for
                  the query.

        Raises:
            MarketDataUnavailable: Provider unreachable or 5xx conditions.
            MarketDataValidationError: Provider payload invalid/unexpected.
            SymbolNotFound: No data for the requested symbols.
            MarketDataRateLimited: Upstream rate limits were exceeded.
            MarketDataQuotaExceeded: Account plan quota exhausted.
            MarketDataBadRequest: Invalid parameters sent upstream.
        """
        ...

    # ------------------------------------------------------------------ #
    # Ingest-side API (used by Marketstack intraday ingest use case)     #
    # ------------------------------------------------------------------ #
    async def fetch_intraday_bars(
        self,
        *,
        symbol: str,
        start: datetime,
        end: datetime,
        interval: str,
        page_size: int = 100,
    ) -> tuple[list[IntradayBarRecord], dict[str, Any]]:
        """Fetch intraday bars for ingest.

        Args:
            symbol:
                Symbol (ticker) to fetch.
            start:
                Inclusive UTC start datetime.
            end:
                Exclusive UTC end datetime.
            interval:
                Provider interval label (short or long form; e.g. "1m",
                "5min", "1h"). The gateway is responsible for normalizing /
                validating this against the provider plan.
            page_size:
                Desired page size for provider requests. The gateway may clamp
                this to the provider's maximum.

        Returns:
            A tuple ``(records, meta)`` where:

                * ``records`` is a list of :class:`IntradayBarRecord`; and
                * ``meta`` may contain additional metadata such as an ``etag``
                  for conditional requests.

        Raises:
            MarketDataUnavailable: Provider unreachable or 5xx conditions.
            MarketDataValidationError: Provider payload invalid/unexpected.
            MarketDataRateLimited: Upstream rate limits were exceeded.
            MarketDataQuotaExceeded: Account plan quota exhausted.
            MarketDataBadRequest: Invalid parameters sent upstream.
        """
        ...


__all__ = [
    "IntradayBarRecord",
    "MarketDataGateway",
]
