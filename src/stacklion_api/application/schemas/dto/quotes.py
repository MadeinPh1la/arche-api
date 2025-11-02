# src/stacklion_api/application/schemas/dto/quotes.py
# Copyright (c) Stacklion.
# SPDX-License-Identifier: MIT
"""Application DTOs for Quotes & Historical Bars.

Synopsis:
    Strict (Pydantic v2) DTOs used by application/use-cases and adapters.
    This module groups both A5 (latest quotes) and A6 (historical quotes)
    DTOs so imports remain stable for tests and outer layers.

Layer:
    application/schemas/dto
"""

from __future__ import annotations

from collections.abc import Sequence
from datetime import datetime
from decimal import Decimal

from pydantic import ConfigDict

from stacklion_api.application.schemas.dto.base import BaseDTO
from stacklion_api.domain.entities.historical_bar import BarInterval


class QuoteDTO(BaseDTO):
    """Latest quote DTO (A5).

    Attributes:
        ticker: Uppercase ticker symbol.
        price: Last traded price.
        currency: ISO currency code (e.g., 'USD').
        as_of: Quote timestamp (UTC).
        volume: Optional last known volume for the tick (provider-dependent).
    """

    model_config = ConfigDict(extra="forbid")

    ticker: str
    price: Decimal
    currency: str
    as_of: datetime
    volume: int | None = None


class QuotesBatchDTO(BaseDTO):
    """Batch of latest quotes (A5)."""

    model_config = ConfigDict(extra="forbid")

    items: list[QuoteDTO]


class HistoricalQueryDTO(BaseDTO):
    """Query parameters for historical quotes (A6).

    Attributes:
        tickers: One or more ticker symbols (uppercase).
        from_: Inclusive UTC start datetime.
        to: Inclusive UTC end datetime.
        interval: Bar interval.
        page: Page number (1-based).
        page_size: Page size (<= 200).
    """

    model_config = ConfigDict(extra="forbid")

    tickers: Sequence[str]
    from_: datetime
    to: datetime
    interval: BarInterval
    page: int = 1
    page_size: int = 200


class HistoricalBarDTO(BaseDTO):
    """DTO for a single OHLCV historical bar (A6).

    Attributes:
        ticker: Uppercase ticker symbol.
        timestamp: UTC timestamp at bar close.
        open: Open price.
        high: High price.
        low: Low price.
        close: Close price.
        volume: Traded volume for the interval (may be None).
        interval: Interval used to aggregate this bar.
    """

    model_config = ConfigDict(extra="forbid")

    ticker: str
    timestamp: datetime
    open: Decimal
    high: Decimal
    low: Decimal
    close: Decimal
    volume: Decimal | None
    interval: BarInterval


__all__ = [
    "QuoteDTO",
    "QuotesBatchDTO",
    "HistoricalQueryDTO",
    "HistoricalBarDTO",
]
