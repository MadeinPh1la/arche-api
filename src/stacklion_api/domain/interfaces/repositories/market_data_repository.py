# src/stacklion_api/domain/interfaces/repositories/market_data_repository.py
# Copyright (c)
# SPDX-License-Identifier: MIT
"""Domain-facing interface for market data repositories.

This module defines:

* IntradayBarRow: write-side representation of an intraday bar used by
  ingestion use cases.
* MarketDataRepository: protocol describing the capabilities required
  from a market data repository implementation.

Notes:
    * This interface is persistence-agnostic; implementations may use
      SQLAlchemy, another ORM, or a raw driver.
    * The concrete adapter implementation in
      ``adapters/repositories/market_data_repository.py`` is expected to
      satisfy this protocol.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from datetime import datetime
from typing import Any, Protocol
from uuid import UUID


@dataclass(frozen=True)
class IntradayBarRow:
    """Write-side representation of an intraday OHLCV bar.

    Attributes:
        symbol_id: Internal UUID of the symbol.
        ts: UTC timestamp of the bar (open time).
        open: Open price as a string to preserve provider precision.
        high: High price as a string.
        low: Low price as a string.
        close: Close price as a string.
        volume: Volume as a string.
        provider: Provider identifier (e.g. ``"marketstack"``).
    """

    symbol_id: UUID
    ts: datetime
    open: str
    high: str
    low: str
    close: str
    volume: str
    provider: str


class MarketDataRepository(Protocol):
    """Domain-level contract for market data repositories."""

    async def upsert_intraday_bars(self, rows: Sequence[IntradayBarRow]) -> int:
        """Insert or update a batch of intraday bars.

        Args:
            rows: Intraday bar write-rows to persist.

        Returns:
            Number of rows processed (inserted or updated).
        """
        raise NotImplementedError

    async def get_latest_intraday_bar(self, symbol_id: UUID) -> Any:
        """Return the latest intraday bar for a symbol, if any.

        Args:
            symbol_id: Internal UUID of the symbol.

        Returns:
            Implementation-specific bar representation or ``None`` when
            no data exists for the symbol.
        """
        raise NotImplementedError
