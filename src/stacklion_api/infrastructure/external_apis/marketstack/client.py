# Copyright (c) Stacklion.
# SPDX-License-Identifier: MIT
"""
Marketstack Gateway.

Summary:
    Async gateway using Marketstack with timeouts, bounded retries, schema
    validation, and domain error translation.

Layer:
    infrastructure/external_apis/marketstack
"""
from __future__ import annotations

from collections.abc import Sequence
from datetime import UTC, datetime
from decimal import Decimal

import httpx
from tenacity import retry, retry_if_exception_type, stop_after_attempt, wait_random_exponential

from stacklion_api.domain.entities.quote import Quote
from stacklion_api.domain.exceptions.market_data import (
    MarketDataUnavailable,
    MarketDataValidationError,
    SymbolNotFound,
)
from stacklion_api.domain.interfaces.gateways.market_data_gateway import MarketDataGatewayProtocol
from stacklion_api.infrastructure.external_apis.marketstack.settings import MarketstackSettings
from stacklion_api.infrastructure.external_apis.marketstack.types import MarketstackLatestResponse


class MarketstackGateway(MarketDataGatewayProtocol):
    """Marketstack-backed market data gateway."""

    def __init__(self, client: httpx.AsyncClient, settings: MarketstackSettings) -> None:
        """Initialize the gateway.

        Args:
            client: Shared HTTP client.
            settings: Marketstack configuration.
        """
        self._client = client
        self._cfg = settings

    def _params_latest(self, tickers: Sequence[str]) -> dict[str, str | int]:
        """Build query params for the latest quotes endpoint."""
        return {
            "access_key": self._cfg.access_key.get_secret_value(),
            "symbols": ",".join(tickers),
            "limit": len(tickers),
        }

    @retry(
        retry=retry_if_exception_type(MarketDataUnavailable),
        wait=wait_random_exponential(multiplier=0.1, max=1.0),
        stop=stop_after_attempt(1),
        reraise=True,
    )
    async def get_latest_quotes(self, tickers: Sequence[str]) -> list[Quote]:
        """Return latest quotes for the provided tickers."""
        url = f"{self._cfg.base_url}/intraday/latest"
        attempts = 0
        while True:
            attempts += 1
            try:
                r = await self._client.get(
                    url,
                    params=self._params_latest(tickers),
                    timeout=self._cfg.timeout_s,
                )
                r.raise_for_status()
                raw: MarketstackLatestResponse = r.json()
            except (httpx.TimeoutException, httpx.NetworkError, httpx.HTTPStatusError) as e:
                if attempts <= self._cfg.max_retries:
                    raise MarketDataUnavailable("market data provider unavailable") from e
                raise MarketDataUnavailable("market data provider unavailable") from e
            except Exception as e:
                raise MarketDataValidationError("invalid provider response") from e

            try:
                # Strict shape validation: must have a list under "data".
                if (
                    not isinstance(raw, dict)
                    or "data" not in raw
                    or not isinstance(raw["data"], list)
                ):
                    raise MarketDataValidationError("unexpected provider payload")

                data = raw["data"]
                items: list[Quote] = []
                for row in data:
                    sym = str(row["symbol"]).upper()
                    price = Decimal(str(row["last"]))
                    ts = datetime.fromisoformat(str(row["date"]).replace("Z", "+00:00")).astimezone(
                        UTC
                    )
                    cur = str(row.get("currency") or "USD")
                    vol = row.get("volume")
                    vol_int = int(vol) if vol is not None else None
                    items.append(
                        Quote(ticker=sym, price=price, currency=cur, as_of=ts, volume=vol_int)
                    )
                if not items:
                    raise SymbolNotFound("no quotes for requested symbols")
                return items
            except SymbolNotFound:
                raise
            except Exception as e:
                raise MarketDataValidationError("unexpected provider payload") from e
