# docs/templates/gateway_example.py
"""Example external API gateway.

Purpose:
- Wrap infra client, normalize responses, and translate errors into domain exceptions.

Layer: adapters

Notes:
- Talks to infrastructure.external_apis.*; exposes domain/application-friendly shapes.
"""

from __future__ import annotations

from collections.abc import Sequence

from stacklion_api.application.schemas.dto.quotes import HistoricalQuoteDTO
from stacklion_api.domain.exceptions import ExternalAPIException
from stacklion_api.infrastructure.external_apis.marketstack.client import MarketstackClient
from stacklion_api.infrastructure.external_apis.marketstack.types import MarketstackBar


class MarketstackGateway:
    """Canonical gateway to Marketstack.

    Args:
        client: Low-level HTTP client wrapper for Marketstack.
    """

    def __init__(self, client: MarketstackClient) -> None:
        self._client = client

    async def get_historical_quotes(self, ticker: str) -> Sequence[HistoricalQuoteDTO]:
        """Fetch historical quotes and normalize to DTOs.

        Args:
            ticker: Canonical ticker symbol.

        Returns:
            Normalized DTOs suitable for use cases.

        Raises:
            ExternalAPIException: On transport errors or invalid payloads.
        """
        try:
            bars: list[MarketstackBar] = await self._client.fetch_historical_bars(ticker=ticker)
        except Exception as exc:  # pragma: no cover - error path
            raise ExternalAPIException("marketstack request failed") from exc

        return [
            HistoricalQuoteDTO(
                ticker=ticker,
                ts=bar.timestamp,
                open=str(bar.open),
                high=str(bar.high),
                low=str(bar.low),
                close=str(bar.close),
                volume=bar.volume,
            )
            for bar in bars
        ]
