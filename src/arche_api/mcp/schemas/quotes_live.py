# src/arche_api/mcp/schemas/quotes_live.py
# Copyright (c) Arche.
# SPDX-License-Identifier: MIT
"""MCP Schemas: Live Quotes.

Purpose:
- Define MCP request/response models for the `quotes.live` method.

Layer: adapters/mcp
"""

from __future__ import annotations

from pydantic import AwareDatetime, BaseModel, ConfigDict, Field


class QuotesLiveParams(BaseModel):
    """Input parameters for the MCP `quotes.live` method."""

    model_config = ConfigDict(extra="forbid")

    tickers: list[str] = Field(
        ...,
        min_length=1,
        description="Ticker symbols (1..50, case-insensitive; normalized to UPPERCASE).",
    )


class MCPQuote(BaseModel):
    """MCP-facing quote snapshot."""

    model_config = ConfigDict(extra="forbid")

    ticker: str = Field(..., description="Upper-case ticker symbol.")
    price: str = Field(..., description="Last price as decimal string.")
    currency: str = Field(..., description="ISO 4217 currency code.")
    as_of: AwareDatetime = Field(
        ...,
        description="Quote timestamp (UTC, ISO-8601).",
    )
    volume: int | None = Field(
        default=None,
        description="Latest volume if available.",
    )


class QuotesLiveResult(BaseModel):
    """Result payload for the MCP `quotes.live` method."""

    model_config = ConfigDict(extra="forbid")

    quotes: list[MCPQuote] = Field(
        ...,
        description="Quotes for requested tickers.",
    )
    request_id: str | None = Field(
        default=None,
        description="Underlying Arche X-Request-ID for correlation.",
    )
    source_status: int = Field(
        ...,
        description="HTTP status returned by the underlying /v2/quotes endpoint.",
    )
