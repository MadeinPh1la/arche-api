# Copyright (c) Stacklion.
# SPDX-License-Identifier: MIT
"""HTTP Schemas: Historical Quotes.

Synopsis:
    Pydantic models that define the HTTP-facing request/response contracts for
    historical quotes. OpenAPI will reference these schemas.

Layer:
    adapters/schemas/http
"""

from __future__ import annotations

from collections.abc import Sequence
from datetime import date
from decimal import Decimal

from pydantic import AwareDatetime, ConfigDict, Field

from stacklion_api.adapters.schemas.http.base import BaseHTTPSchema


class QuoteItem(BaseHTTPSchema):
    """HTTP schema for a single quote item."""

    ticker: str = Field(description="Upper-case ticker symbol", examples=["MSFT"])
    price: str = Field(description="Decimal string last price", examples=["428.17"])
    currency: str = Field(description="ISO 4217 currency", examples=["USD"])
    as_of: AwareDatetime = Field(
        description="UTC timestamp (ISO-8601)", examples=["2025-10-28T12:34:56Z"]
    )
    volume: int | None = Field(
        default=None, description="Latest volume if available", examples=[14230000]
    )


class QuotesBatch(BaseHTTPSchema):
    """HTTP schema for a batch of quotes (wrapped by SuccessEnvelope)."""

    items: list[QuoteItem] = Field(description="Quotes for requested tickers (≤50)")


class HistoricalQuotesRequest(BaseHTTPSchema):
    """Query parameters for /v2/quotes/historical."""

    model_config = ConfigDict(extra="forbid")

    tickers: Sequence[str] = Field(
        ..., description="List of ticker symbols (1..50).", examples=[["AAPL", "MSFT"]]
    )
    from_: date = Field(..., description="Start date (UTC).", examples=["2025-01-01"])
    to: date = Field(..., description="End date (UTC, inclusive).", examples=["2025-03-31"])
    interval: str = Field(..., description="Bar interval (1m,5m,15m,1h,1d).", examples=["1d"])
    page: int = Field(1, ge=1, description="Page number.")
    page_size: int = Field(50, ge=1, le=200, description="Page size (max 200).")


class HistoricalBarHTTP(BaseHTTPSchema):
    """HTTP payload for a single bar.

    Numeric fields use Decimal in the schema so that:
      * Application/DTO layers can pass Decimal instances directly.
      * BaseHTTPSchema's encoders serialize them deterministically as strings
        on the wire, preserving precision for clients.
    """

    model_config = ConfigDict(extra="forbid")

    ticker: str = Field(...)
    timestamp: AwareDatetime = Field(..., description="Bar timestamp (UTC, ISO-8601).")
    open: Decimal = Field(..., description="Open price as decimal.")
    high: Decimal = Field(..., description="High price as decimal.")
    low: Decimal = Field(..., description="Low price as decimal.")
    close: Decimal = Field(..., description="Close price as decimal.")
    volume: Decimal | None = Field(
        default=None, description="Volume as decimal; may be null if unavailable."
    )
    interval: str = Field(..., description="Bar interval identifier (e.g., 1d, 1m).")


class HistoricalQuotesPaginatedResponse(BaseHTTPSchema):
    """Paginated list of historical bars."""

    model_config = ConfigDict(extra="forbid")

    page: int
    page_size: int
    total: int
    items: list[HistoricalBarHTTP]
