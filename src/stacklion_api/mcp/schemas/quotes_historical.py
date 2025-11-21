# src/stacklion_api/mcp/schemas/quotes_historical.py
# Copyright (c) Stacklion.
# SPDX-License-Identifier: MIT
"""MCP Schemas: Historical Quotes.

Purpose:
- Define MCP request/response models for the `quotes.historical` method.

Layer: adapters/mcp
"""

from __future__ import annotations

from datetime import date

from pydantic import AwareDatetime, BaseModel, ConfigDict, Field


class QuotesHistoricalParams(BaseModel):
    """Input parameters for the MCP `quotes.historical` method."""

    model_config = ConfigDict(
        extra="forbid",
    )

    tickers: list[str] = Field(
        ...,
        min_length=1,
        description="Ticker symbols (1..50, case-insensitive; normalized to UPPERCASE).",
    )
    from_: date = Field(
        ...,
        alias="from",
        description="Start date (UTC, inclusive).",
    )
    to: date = Field(
        ...,
        description="End date (UTC, inclusive).",
    )
    interval: str = Field(
        ...,
        description="Bar interval (currently supports 1d and 1m).",
    )
    page: int = Field(
        default=1,
        ge=1,
        description="1-based page number.",
    )
    page_size: int = Field(
        default=50,
        ge=1,
        le=200,
        description="Items per page (recommended max 200 for MCP clients).",
    )


class MCPHistoricalBar(BaseModel):
    """MCP-facing representation of a historical OHLCV bar."""

    model_config = ConfigDict(extra="forbid")

    ticker: str = Field(..., description="Upper-case ticker.")
    timestamp: AwareDatetime = Field(..., description="Bar timestamp (UTC, ISO-8601).")
    open: str = Field(..., description="Open price as decimal string.")
    high: str = Field(..., description="High price as decimal string.")
    low: str = Field(..., description="Low price as decimal string.")
    close: str = Field(..., description="Close price as decimal string.")
    volume: str | None = Field(
        default=None,
        description="Volume as decimal string; may be null if unavailable.",
    )
    interval: str = Field(..., description="Bar interval identifier (e.g., 1d, 1m).")


class QuotesHistoricalResult(BaseModel):
    """Result payload for the MCP `quotes.historical` method."""

    model_config = ConfigDict(extra="forbid")

    items: list[MCPHistoricalBar] = Field(
        ...,
        description="Historical OHLCV bars.",
    )
    page: int = Field(..., description="Current page number.")
    page_size: int = Field(..., description="Page size.")
    total: int = Field(..., description="Total item count for the filter.")
    request_id: str | None = Field(
        default=None,
        description="Underlying Stacklion X-Request-ID for correlation.",
    )
    source_status: int = Field(
        ...,
        description="HTTP status returned by the underlying /v2/quotes/historical endpoint.",
    )
