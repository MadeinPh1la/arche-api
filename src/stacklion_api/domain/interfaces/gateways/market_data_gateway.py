# Copyright (c) Stacklion.
# SPDX-License-Identifier: MIT
"""
Market Data Gateway Protocol

Purpose:
    Protocol (interface) for retrieving market quotes from an external provider.

Layer: domain/interfaces/gateways
"""
from __future__ import annotations

from collections.abc import Sequence
from typing import Protocol

from stacklion_api.domain.entities.quote import Quote


class MarketDataGatewayProtocol(Protocol):
    """Abstraction over external market data providers.

    Args:
        tickers: Sequence of ticker symbols (upper-case).

    Returns:
        list[Quote]: Latest quotes matching the requested tickers.

    Raises:
        MarketDataUnavailable: When the provider is down or timed out.
        MarketDataValidationError: When the provider payload is invalid.
    """

    async def get_latest_quotes(self, tickers: Sequence[str]) -> list[Quote]: ...
