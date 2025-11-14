# Copyright (c)
# SPDX-License-Identifier: MIT
"""Application Port: Market data gateway (ingest primitives).

This interface defines provider-agnostic, ingest-oriented capabilities used by
use-cases to fetch *normalized* market data without binding to any provider
SDK, HTTP client, or read-side DTOs.

Design:
    * Capability-oriented: fetch intraday bars for a bounded UTC window.
    * Provider-agnostic normalized shape (strings for numeric precision).
    * Metadata bag for transport concerns (e.g., ETag, paging cursors).
"""

from __future__ import annotations

from datetime import datetime
from typing import Any, Protocol, TypedDict


class IntradayBarRecord(TypedDict):
    """Normalized intraday bar record (provider-agnostic).

    All numeric values are strings to preserve precision until persistence.
    """

    symbol: str  # Upper-cased ticker (e.g., "MSFT")
    ts: str  # ISO-8601 UTC, e.g., "2025-11-11T10:00:00Z"
    open: str
    high: str
    low: str
    close: str
    volume: str  # integer as string


class MarketDataGateway(Protocol):
    """Protocol for ingest-oriented market data fetching."""

    async def fetch_intraday_bars(
        self,
        *,
        symbol: str,
        start: datetime,
        end: datetime,
        interval: str,
        page_size: int = 1000,
    ) -> tuple[list[IntradayBarRecord], dict[str, Any]]:
        """Fetch a bounded set of intraday bars (normalized).

        Args:
            symbol: Ticker symbol (case-insensitive).
            start: Inclusive start of window (UTC).
            end: Exclusive end of window (UTC).
            interval: Provider interval label (e.g., "1m", "5m").
            page_size: Maximum rows to request (provider limit permitting).

        Returns:
            tuple[list[IntradayBarRecord], dict]: (records, metadata).
            The metadata dict may include keys like "etag" or paging tokens.
        """
