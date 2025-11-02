# Copyright (c) Stacklion.
# SPDX-License-Identifier: MIT
"""Adapter Gateway: Marketstack → Application DTOs.

Synopsis:
    Bridges the Marketstack client (infrastructure) and the application layer
    by mapping provider payloads into `HistoricalBarDTO` instances.

Layer:
    adapters/gateways
"""

from __future__ import annotations

from datetime import datetime
from decimal import Decimal

from src.application.interfaces.market_data_gateway import (
    MarketDataGateway as MarketDataGatewayProtocol,
)
from src.application.schemas.dto.quotes import HistoricalBarDTO, HistoricalQueryDTO
from src.domain.entities.historical_bar import BarInterval
from src.domain.exceptions.market_data import (
    MarketDataUnavailable,
    MarketDataValidationError,
)
from src.infrastructure.external_apis.marketstack_client import MarketstackClient


class MarketDataGateway(MarketDataGatewayProtocol):
    """Marketstack-backed market data gateway."""

    def __init__(self, client: MarketstackClient):
        """Initialize the gateway.

        Args:
            client: Marketstack HTTP client.
        """
        self._client = client

    async def fetch(self, q: HistoricalQueryDTO) -> tuple[list[HistoricalBarDTO], int]:
        """Fetch and map provider payload to DTOs.

        Args:
            q: Query parameters.

        Returns:
            Tuple of (items, total).

        Raises:
            MarketDataUnavailable: On network or 5xx errors.
            MarketDataBadRequest: On upstream parameter errors.
            MarketDataRateLimited: When rate limit is hit.
            MarketDataQuotaExceeded: When plan quota is exhausted.
            MarketDataValidationError: On unexpected payload shapes.
        """
        try:
            if q.interval == BarInterval.I1D:
                payload = await self._client.eod(
                    tickers=q.tickers,
                    date_from=q.from_.date().isoformat(),
                    date_to=q.to.date().isoformat(),
                    page=q.page,
                    limit=q.page_size,
                )
            else:
                payload = await self._client.intraday(
                    tickers=q.tickers,
                    date_from=q.from_.isoformat(),
                    date_to=q.to.isoformat(),
                    interval=q.interval.value,
                    page=q.page,
                    limit=q.page_size,
                )
        except Exception as exc:  # httpx errors, etc.
            raise MarketDataUnavailable("Upstream request failed") from exc

        try:
            raw_items = payload.get("data", [])
            pagination = payload.get("pagination", {})
            items: list[HistoricalBarDTO] = []
            for row in raw_items:
                items.append(
                    HistoricalBarDTO(
                        ticker=str(row["symbol"]).upper(),
                        timestamp=datetime.fromisoformat(str(row["date"]).replace("Z", "+00:00")),
                        open=Decimal(str(row["open"])),
                        high=Decimal(str(row["high"])),
                        low=Decimal(str(row["low"])),
                        close=Decimal(str(row["close"])),
                        volume=(
                            Decimal(str(row["volume"])) if row.get("volume") is not None else None
                        ),
                        interval=q.interval,
                    )
                )
            total = int(pagination.get("total", len(items)))
            return items, total
        except KeyError as exc:
            raise MarketDataValidationError(f"Missing field in payload: {exc}") from exc
        except Exception as exc:  # Decimal/parse issues
            raise MarketDataValidationError(f"Invalid payload: {exc}") from exc
