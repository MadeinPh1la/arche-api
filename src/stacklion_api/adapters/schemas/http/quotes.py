# Copyright (c) Stacklion.
# SPDX-License-Identifier: MIT
"""
HTTP Schemas – Quotes

Purpose:
    Transport-facing Pydantic models for `/v1/quotes` responses.

Layer: adapters/schemas/http
"""
from __future__ import annotations

from pydantic import AwareDatetime, Field

from .base import BaseHTTPSchema


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
